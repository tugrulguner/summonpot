"""Compile private operation validators without serializing application values.

This relies on the tested Pydantic 2.13.5 / pydantic-core 2.46.5 schema
contract and the private ``_use_prebuilt`` compiler option. Dependency upgrades
must run the adversarial regression suite: allowing prebuilt validators silently
restores the model class's default (non-revalidating) instance behavior. Never
fall back to the original adapter if compilation fails.
"""

from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from dataclasses import is_dataclass
from typing import Any, cast

from pydantic import BaseModel, TypeAdapter
from pydantic_core import SchemaValidator, core_schema

_mapping_namespaces: ContextVar[
    dict[int, tuple[dict[Any, Any], frozenset[str], frozenset[str]]] | None
] = ContextVar("output_mapping_namespaces", default=None)


def _input_kind(value: Any) -> str:
    return (
        "instance"
        if isinstance(value, BaseModel)
        or (is_dataclass(value) and not isinstance(value, type))
        else "input"
    )


def _separate_model_extras(model: dict[str, Any]) -> dict[str, Any]:
    """Keep colliding extras out of core's instance-dict merge.

    Before validators receive canonical fields plus non-colliding extras, just as
    mapping validation does. After and outer wrap validators receive the
    reconstructed model with non-colliding extras preserved; colliding extras are
    rejected because one mapping cannot represent both namespaces.
    A per-model ContextVar carries only the detached collision dictionary to the
    model-fields schema. Tokens make recursive/reentrant validation independent.
    """
    pending: ContextVar[tuple[dict[str, Any], bool] | None] = ContextVar(
        "output_extras", default=None
    )
    field_names: set[str] = set()
    emitted_names: set[str] = set()

    def split(value: Any) -> tuple[Any, dict[str, Any]]:
        state = pending.get()
        if state is None:
            return value, {}
        collisions, internal_slot = state
        if internal_slot and isinstance(value, dict):
            value = {
                key: item for key, item in value.items() if key != "__pydantic_extra__"
            }
        return value, collisions

    def join(value: Any) -> Any:
        (fields, extras, fields_set), collisions = value
        combined = {**(extras or {}), **collisions}
        shadowed = (field_names | emitted_names).intersection(combined)
        if shadowed:
            names = ", ".join(repr(name) for name in sorted(shadowed))
            raise ValueError(
                f"output extras shadow declared serialized field keys: {names}"
            )
        return fields, combined, fields_set

    def replace_fields(schema: dict[str, Any]) -> dict[str, Any]:
        if schema.get("type") == "model-fields":
            field_names.update(schema["fields"])
            emitted_names.update(
                field.get("serialization_alias", name)
                for name, field in schema["fields"].items()
                if not field.get("serialization_exclude")
            )
            emitted_names.update(
                field.get("alias", field["property_name"])
                for field in schema.get("computed_fields", [])
            )
            extra_schema = core_schema.dict_schema(
                keys_schema=schema.get("extras_keys_schema", core_schema.str_schema()),
                values_schema=schema.get("extras_schema", core_schema.any_schema()),
            )
            return cast(
                dict[str, Any],
                core_schema.no_info_after_validator_function(
                    join,
                    core_schema.no_info_before_validator_function(
                        split,
                        core_schema.tuple_positional_schema(
                            [cast(core_schema.CoreSchema, schema), extra_schema]
                        ),
                    ),
                ),
            )
        # Model before/wrap hooks surround model-fields; do not descend into
        # field schemas or reference definitions belonging to other models.
        if "schema" in schema:
            return {**schema, "schema": replace_fields(schema["schema"])}
        return schema

    inner = {**model, "schema": replace_fields(model["schema"])}

    def detach(value: Any, handler: Any) -> Any:
        if not isinstance(value, model["cls"]):
            return handler(value)
        extras = value.__pydantic_extra__ or {}
        collisions = {key: item for key, item in extras.items() if key in field_names}
        # Do not invoke application copy hooks or write to the caller's storage.
        detached = object.__new__(type(value))
        storage = value.__dict__.copy()
        # Pydantic model_construct can place this annotated internal slot in
        # __dict__ as well; it is not a declared field or an additional extra.
        storage.pop("__pydantic_extra__", None)
        object.__setattr__(detached, "__dict__", storage)
        object.__setattr__(
            detached,
            "__pydantic_extra__",
            {key: item for key, item in extras.items() if key not in field_names},
        )
        object.__setattr__(
            detached, "__pydantic_fields_set__", value.__pydantic_fields_set__.copy()
        )
        private = value.__pydantic_private__
        object.__setattr__(
            detached,
            "__pydantic_private__",
            None if private is None else private.copy(),
        )
        token = pending.set((collisions, "__pydantic_extra__" in detached.__dict__))
        try:
            return handler(detached)
        finally:
            pending.reset(token)

    return cast(
        dict[str, Any],
        core_schema.no_info_wrap_validator_function(
            detach, cast(core_schema.CoreSchema, inner)
        ),
    )


def _reject_ambiguous_object_namespaces(schema: Any) -> None:
    """Reject duplicate direct keys in validation and serialization namespaces."""
    seen_nodes: set[int] = set()

    def reject_serialization(
        fields: list[tuple[str, dict[str, Any]]], owner: str
    ) -> None:
        emitted: dict[str, str] = {}
        for name, field in fields:
            if field.get("serialization_exclude"):
                continue
            key = field.get("serialization_alias", field.get("alias", name))
            previous = emitted.get(key)
            if previous is not None:
                raise TypeError(
                    f"Output shape {owner!r} emits fields {previous!r} and {name!r} "
                    f"as duplicate JSON key {key!r}."
                )
            emitted[key] = name

    def direct_validation_keys(
        name: str, field: dict[str, Any], *, validate_by_alias: bool
    ) -> set[str]:
        alias = field.get("validation_alias")
        if alias is None:
            return {name}
        if not validate_by_alias:
            return set()
        if isinstance(alias, str):
            return {alias}
        if isinstance(alias, list):
            if len(alias) == 1 and isinstance(alias[0], str):
                return {alias[0]}
            return {
                path[0]
                for path in alias
                if isinstance(path, list)
                and len(path) == 1
                and isinstance(path[0], str)
            }
        return set()

    def reject_validation(
        fields: list[tuple[str, dict[str, Any]]],
        owner: str,
        *,
        validate_by_alias: bool,
        validate_by_name: bool,
    ) -> None:
        accepted: dict[str, str] = {}
        for name, field in fields:
            keys = direct_validation_keys(
                name, field, validate_by_alias=validate_by_alias
            )
            if validate_by_name:
                keys.add(name)
            for key in keys:
                previous = accepted.get(key)
                if previous is not None and previous != name:
                    raise TypeError(
                        f"Output shape {owner!r} accepts fields {previous!r} and "
                        f"{name!r} from duplicate validation key {key!r}."
                    )
                accepted[key] = name

    def inspect(
        node: Any, owner: str = "output", config: dict[str, Any] | None = None
    ) -> None:
        if isinstance(node, dict):
            identity = id(node)
            if identity in seen_nodes:
                return
            seen_nodes.add(identity)
            node_type = node.get("type")
            current_owner = getattr(node.get("cls"), "__qualname__", owner)
            current_config = node.get("config", config)
            if isinstance(node_type, str) and node_type in {
                "model-fields",
                "typed-dict",
            }:
                fields = list(node.get("fields", {}).items())
                emitted_fields = [*fields]
                emitted_fields.extend(
                    (field["property_name"], field)
                    for field in node.get("computed_fields", [])
                )
                reject_serialization(emitted_fields, current_owner)
                reject_validation(
                    fields,
                    current_owner,
                    validate_by_alias=bool(
                        not current_config
                        or current_config.get("validate_by_alias", True)
                    ),
                    validate_by_name=bool(
                        current_config and current_config.get("validate_by_name", False)
                    ),
                )
            elif node_type == "dataclass-args":
                fields = [(field["name"], field) for field in node.get("fields", [])]
                emitted_fields = [
                    (name, field)
                    for name, field in fields
                    if not field.get("init_only")
                ]
                emitted_fields.extend(
                    (field["property_name"], field)
                    for field in node.get("computed_fields", [])
                )
                reject_serialization(emitted_fields, current_owner)
                reject_validation(
                    fields,
                    current_owner,
                    validate_by_alias=bool(
                        not current_config
                        or current_config.get("validate_by_alias", True)
                    ),
                    validate_by_name=bool(
                        current_config and current_config.get("validate_by_name", False)
                    ),
                )
            serialization = node.get("serialization")
            if isinstance(serialization, dict) and "return_schema" in serialization:
                inspect(serialization["return_schema"], current_owner, current_config)
            for key, value in node.items():
                if key not in {"config", "default", "metadata", "serialization"}:
                    inspect(value, current_owner, current_config)
        elif isinstance(node, (list, tuple)):
            for value in node:
                inspect(value, owner, config)

    inspect(schema)


def _reject_callable_output_discriminators(schema: Any) -> None:
    """Reject branch selection that the final audit cannot replay inertly."""
    seen: set[int] = set()

    def inspect(node: Any) -> None:
        if isinstance(node, dict):
            identity = id(node)
            if identity in seen:
                return
            seen.add(identity)
            if node.get("type") == "tagged-union" and callable(
                node.get("discriminator")
            ):
                raise TypeError(
                    "Callable discriminators are unsupported for runtime-enforced "
                    "operation outputs; use a field-name discriminator instead."
                )
            for value in dict.values(node):
                inspect(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                inspect(value)

    inspect(schema)


def _runtime_model_extra_collision_auditor(schema: Any) -> Any:
    """Build a final schema-aware storage audit without application hooks."""
    dataclass_fields: list[tuple[type[Any], tuple[str, ...]]] = []
    definitions: dict[str, dict[str, Any]] = {}
    seen_schema: set[int] = set()

    def collect_dataclasses(node: Any) -> None:
        if isinstance(node, dict):
            identity = id(node)
            if identity in seen_schema:
                return
            seen_schema.add(identity)
            if node.get("type") == "dataclass" and isinstance(node.get("cls"), type):
                dataclass_fields.append((node["cls"], tuple(node.get("fields", ()))))
            reference = node.get("ref")
            if isinstance(reference, str):
                definitions[reference] = node
            for value in dict.values(node):
                collect_dataclasses(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                collect_dataclasses(value)

    collect_dataclasses(schema)

    container_types = {
        "list": list,
        "tuple": tuple,
        "dict": dict,
        "set": set,
        "frozenset": frozenset,
    }

    def declared_container_type(node: Any) -> type[Any] | None:
        """Resolve concrete built-in container schemas through transparent wrappers."""
        if not isinstance(node, dict):
            return None
        node_type = node.get("type")
        direct = container_types.get(node_type) if isinstance(node_type, str) else None
        if direct is not None:
            return direct
        if node_type == "definition-ref":
            reference = node.get("schema_ref")
            return declared_container_type(
                definitions.get(reference) if isinstance(reference, str) else None
            )
        if node_type == "definitions":
            return declared_container_type(node.get("schema"))
        if node_type in {
            "default",
            "function-after",
            "function-before",
            "function-plain",
            "function-wrap",
            "custom-error",
            "json",
        }:
            return declared_container_type(node.get("schema"))
        if node_type == "chain":
            steps = node.get("steps", ())
            return declared_container_type(steps[-1]) if steps else None
        if node_type in {"json-or-python", "lax-or-strict"}:
            # A concrete deque is represented as a lax list conversion plus a
            # strict instance branch. Derive its public result type from that
            # branch rather than mistaking the implementation list for output.
            pending = [
                node.get("strict_schema"),
                node.get("python_schema"),
            ]
            while pending:
                candidate = pending.pop()
                if not isinstance(candidate, dict):
                    continue
                if (
                    candidate.get("type") == "is-instance"
                    and candidate.get("cls") is deque
                ):
                    return deque
                candidate_type = candidate.get("type")
                if candidate_type == "chain":
                    pending.extend(candidate.get("steps", ()))
                elif candidate_type in {"json-or-python", "lax-or-strict"}:
                    pending.extend(
                        (
                            candidate.get("strict_schema"),
                            candidate.get("python_schema"),
                        )
                    )
            branches = (
                (node.get("python_schema"), node.get("json_schema"))
                if node_type == "json-or-python"
                else (node.get("lax_schema"), node.get("strict_schema"))
            )
            resolved = {declared_container_type(branch) for branch in branches}
            resolved.discard(None)
            if len(resolved) == 1:
                return resolved.pop()
        return None

    def container_items_schema(node: Any, expected: type[Any]) -> Any:
        """Find the item schema hidden by a concrete container wrapper."""
        if not isinstance(node, dict):
            return None
        node_type = node.get("type")
        if expected is deque and node_type == "list":
            return node.get("items_schema")
        if node_type == expected.__name__:
            return node.get("items_schema")
        if node_type == "definition-ref":
            reference = node.get("schema_ref")
            return container_items_schema(
                definitions.get(reference) if isinstance(reference, str) else None,
                expected,
            )
        for key in (
            "schema",
            "lax_schema",
            "strict_schema",
            "python_schema",
            "json_schema",
        ):
            found = container_items_schema(node.get(key), expected)
            if found is not None:
                return found
        if node_type == "chain":
            for step in reversed(node.get("steps", ())):
                found = container_items_schema(step, expected)
                if found is not None:
                    return found
        return None

    def concrete_container_schema(node: Any, expected: type[Any]) -> Any:
        """Return the concrete node that owns a container's child schemas."""
        if not isinstance(node, dict):
            return None
        node_type = node.get("type")
        if node_type == expected.__name__ or (
            expected is deque and node_type == "list"
        ):
            return node
        if node_type == "definition-ref":
            reference = node.get("schema_ref")
            return concrete_container_schema(
                definitions.get(reference) if isinstance(reference, str) else None,
                expected,
            )
        for key in (
            "schema",
            "lax_schema",
            "strict_schema",
            "python_schema",
            "json_schema",
        ):
            found = concrete_container_schema(node.get(key), expected)
            if found is not None:
                return found
        if node_type == "chain":
            for step in reversed(node.get("steps", ())):
                found = concrete_container_schema(step, expected)
                if found is not None:
                    return found
        return None

    scalar_types = {
        "bool": bool,
        "bytes": bytes,
        "complex": complex,
        "dict": dict,
        "float": float,
        "frozenset": frozenset,
        "int": int,
        "list": list,
        "none": type(None),
        "set": set,
        "str": str,
        "tuple": tuple,
    }

    _missing = object()
    literal_primitive_equality = {
        bool: bool.__eq__,
        bytes: bytes.__eq__,
        complex: complex.__eq__,
        float: float.__eq__,
        int: int.__eq__,
        str: str.__eq__,
        type(None): lambda left, right: left is right,
    }

    def safe_literal_equal(current: Any, expected: Any) -> bool:
        """Compare exact primitive Literal values without application dispatch."""
        if current is expected:
            return True
        current_type = type(current)
        if current_type is not type(expected):
            return False
        equality = literal_primitive_equality.get(current_type)
        if equality is None:
            return False
        return equality(current, expected) is True

    def exact_dict_value(current: dict[Any, Any], key: Any) -> Any:
        """Read a primitive key from exact dict storage without key hooks."""
        for stored_key, value in zip(
            dict.__iter__(current), dict.values(current), strict=True
        ):
            if safe_literal_equal(stored_key, key):
                return value
        return _missing

    def discriminator_paths(discriminator: Any) -> tuple[tuple[str | int, ...], ...]:
        if type(discriminator) is str:
            return ((discriminator,),)
        if type(discriminator) is not list or not discriminator:
            return ()
        if all(type(path) is list for path in discriminator):
            raw_paths = discriminator
        else:
            raw_paths = (discriminator,)
        paths: list[tuple[str | int, ...]] = []
        for raw_path in raw_paths:
            if not raw_path or not all(type(part) in {str, int} for part in raw_path):
                return ()
            paths.append(tuple(raw_path))
        return tuple(paths)

    def discriminator_step(current: Any, part: str | int) -> Any:
        if type(current) is dict:
            return exact_dict_value(current, part)
        if BaseModel in type(current).__mro__:
            storage = object.__getattribute__(current, "__dict__")
            if type(storage) is not dict:
                return _missing
            value = exact_dict_value(storage, part)
            if value is not _missing:
                return value
            extras = object.__getattribute__(current, "__pydantic_extra__")
            if type(extras) is dict:
                return exact_dict_value(extras, part)
            return _missing
        if type(part) is int and type(current) is list:
            length = list.__len__(current)
            if -length <= part < length:
                return list.__getitem__(current, part)
        if type(part) is int and type(current) is tuple:
            length = tuple.__len__(current)
            if -length <= part < length:
                return tuple.__getitem__(current, part)
        return _missing

    def tagged_union_choice(current: Any, node: dict[str, Any]) -> Any:
        choices = node.get("choices")
        if type(choices) is not dict:
            return _missing
        for path in discriminator_paths(node.get("discriminator")):
            tag = current
            for part in path:
                tag = discriminator_step(tag, part)
                if tag is _missing:
                    break
            if tag is _missing:
                continue
            for expected, choice in zip(
                dict.__iter__(choices), dict.values(choices), strict=True
            ):
                if safe_literal_equal(tag, expected):
                    return choice[0] if type(choice) is tuple else choice
        return _missing

    def schema_match_score(
        current: Any,
        node: Any,
        active: set[tuple[int, int]] | None = None,
    ) -> int | None:
        """Score structural runtime evidence for one union branch.

        ``None`` is a proven mismatch. Non-negative scores are compatible, with
        larger values carrying more exact runtime evidence. Inspection is limited to
        exact built-in storage and object-owned model/dataclass storage: branch
        selection must not rerun validators or invoke application iteration,
        equality, representation, or hashing hooks.
        """
        if not isinstance(node, dict):
            return 0
        if active is None:
            active = set()
        marker = (id(current), id(node))
        if marker in active:
            return 0
        active.add(marker)
        try:
            node_type = node.get("type")
            if node_type == "definition-ref":
                reference = node.get("schema_ref")
                return schema_match_score(
                    current,
                    definitions.get(reference) if isinstance(reference, str) else None,
                    active,
                )
            if node_type == "definitions":
                return schema_match_score(current, node.get("schema"), active)
            if node_type == "nullable":
                if current is None:
                    return 1
                return schema_match_score(current, node.get("schema"), active)
            if node_type in {
                "default",
                "function-after",
                "function-before",
                "function-plain",
                "function-wrap",
                "custom-error",
                "json",
            }:
                return schema_match_score(current, node.get("schema"), active)
            if node_type == "chain":
                steps = node.get("steps", ())
                return schema_match_score(current, steps[-1], active) if steps else 0
            if node_type in {"json-or-python", "lax-or-strict"}:
                branches = (
                    (node.get("python_schema"), node.get("json_schema"))
                    if node_type == "json-or-python"
                    else (node.get("lax_schema"), node.get("strict_schema"))
                )
                scores = [
                    score
                    for branch in branches
                    if (score := schema_match_score(current, branch, active))
                    is not None
                ]
                return max(scores) if scores else None

            if node_type == "tagged-union":
                selected = tagged_union_choice(current, node)
                if selected is _missing:
                    return None
                return schema_match_score(current, selected, active)

            if node_type == "union":
                choices = node.get("choices", ())
                values = choices.values() if isinstance(choices, dict) else choices
                scores = [
                    score
                    for choice in values
                    if (
                        score := schema_match_score(
                            current,
                            choice[0] if isinstance(choice, tuple) else choice,
                            active,
                        )
                    )
                    is not None
                ]
                return max(scores) if scores else None

            expected = declared_container_type(node)
            if expected is not None:
                if type(current) is not expected:
                    return None
                concrete = concrete_container_schema(node, expected) or {}
                score = 1
                children: list[tuple[Any, Any]] = []
                if expected is dict:
                    keys_schema = concrete.get("keys_schema")
                    values_schema = concrete.get("values_schema")
                    children.extend(
                        zip(dict.__iter__(current), dict.values(current), strict=True)
                    )
                    child_schemas = (keys_schema, values_schema)
                    for key, item in children:
                        for child, child_schema in zip(
                            (key, item), child_schemas, strict=True
                        ):
                            child_score = schema_match_score(
                                child, child_schema, active
                            )
                            if child_score is None:
                                return None
                            score += child_score
                    return score
                if expected is tuple:
                    item_schemas = concrete.get("items_schema", ())
                    variadic_index = concrete.get("variadic_item_index")
                    for index, item in enumerate(tuple.__iter__(current)):
                        child_schema = None
                        if index < len(item_schemas):
                            child_schema = item_schemas[index]
                        elif isinstance(variadic_index, int) and variadic_index < len(
                            item_schemas
                        ):
                            child_schema = item_schemas[variadic_index]
                        child_score = schema_match_score(item, child_schema, active)
                        if child_score is None:
                            return None
                        score += child_score
                    return score
                items_schema = container_items_schema(node, expected)
                iterator = {
                    list: list.__iter__,
                    set: set.__iter__,
                    frozenset: frozenset.__iter__,
                    deque: deque.__iter__,
                }[expected]
                for item in iterator(current):
                    child_score = schema_match_score(item, items_schema, active)
                    if child_score is None:
                        return None
                    score += child_score
                return score

            scalar = scalar_types.get(node_type) if isinstance(node_type, str) else None
            if scalar is not None:
                return 1 if type(current) is scalar else None
            if node_type in {"model", "dataclass"}:
                cls = node.get("cls")
                if not isinstance(cls, type) or cls not in type(current).__mro__:
                    return None
                return 2 if type(current) is cls else 1
            if node_type == "is-instance":
                cls = node.get("cls")
                if not isinstance(cls, type) or cls not in type(current).__mro__:
                    return None
                return 2 if type(current) is cls else 1
            if node_type == "typed-dict":
                if type(current) is not dict:
                    return None
                fields = node.get("fields", {})
                pairs = tuple(
                    zip(dict.__iter__(current), dict.values(current), strict=True)
                )
                string_values = {key: item for key, item in pairs if type(key) is str}
                required = {
                    name
                    for name, field in fields.items()
                    if field.get("required", True)
                }
                if not required.issubset(string_values):
                    return None
                score = 1 + len(required)
                for name, field in fields.items():
                    if name not in string_values:
                        continue
                    child_score = schema_match_score(string_values[name], field, active)
                    if child_score is None:
                        return None
                    score += child_score
                return score
            if node_type == "typed-dict-field" or node_type == "model-field":
                return schema_match_score(current, node.get("schema"), active)
            if node_type == "literal":
                return (
                    2
                    if any(
                        safe_literal_equal(current, expected)
                        for expected in node.get("expected", ())
                    )
                    else None
                )
            if node_type == "any":
                return 0
            return 0
        finally:
            active.remove(marker)

    def dataclass_storage(value: Any) -> tuple[dict[Any, Any], ...]:
        state = object.__getstate__(value)
        if isinstance(state, dict):
            return (state,)
        if isinstance(state, tuple):
            return tuple(item for item in state if isinstance(item, dict))
        return ()

    def schema_audit(value: Any) -> None:
        """Follow schema-owned storage after outer validators may replace values."""
        seen: set[tuple[int, int]] = set()

        def inspect_schema(current: Any, node: Any) -> None:
            if not isinstance(node, dict):
                return
            marker = (id(current), id(node))
            if marker in seen:
                return
            seen.add(marker)
            node_type = node.get("type")

            if node_type == "definitions":
                inspect_schema(current, node.get("schema"))
                return
            if node_type == "definition-ref":
                reference = node.get("schema_ref")
                if isinstance(reference, str):
                    inspect_schema(current, definitions.get(reference))
                return
            if node_type == "nullable" and current is None:
                return
            expected_container = declared_container_type(node)
            if expected_container is not None:
                if type(current) is not expected_container:
                    raise ValueError(
                        "output container storage must use the exact built-in "
                        f"{expected_container.__name__} type"
                    )
                concrete = concrete_container_schema(node, expected_container) or {}
                if expected_container is dict:
                    values_schema = concrete.get("values_schema")
                    for item in dict.values(current):
                        inspect_schema(item, values_schema)
                    return
                if expected_container is tuple:
                    item_schemas = concrete.get("items_schema", ())
                    variadic_index = concrete.get("variadic_item_index")
                    for index, item in enumerate(tuple.__iter__(current)):
                        if index < len(item_schemas):
                            inspect_schema(item, item_schemas[index])
                        elif isinstance(variadic_index, int) and variadic_index < len(
                            item_schemas
                        ):
                            inspect_schema(item, item_schemas[variadic_index])
                    return
                items_schema = container_items_schema(node, expected_container)
                iterator = {
                    list: list.__iter__,
                    tuple: tuple.__iter__,
                    set: set.__iter__,
                    frozenset: frozenset.__iter__,
                    deque: deque.__iter__,
                }[expected_container]
                for item in iterator(current):
                    inspect_schema(item, items_schema)
                return
            if node_type in {
                "default",
                "function-after",
                "function-before",
                "function-plain",
                "function-wrap",
                "nullable",
                "custom-error",
                "json",
            }:
                inspect_schema(current, node.get("schema"))
                return
            if node_type == "lax-or-strict":
                inspect_schema(current, node.get("lax_schema"))
                inspect_schema(current, node.get("strict_schema"))
                return
            if node_type == "model":
                cls = node.get("cls")
                if not isinstance(cls, type) or not any(
                    base is cls for base in type(current).__mro__
                ):
                    return
                if node.get("root_model"):
                    storage = object.__getattribute__(current, "__dict__")
                    if dict.__contains__(storage, "root"):
                        inspect_schema(
                            dict.__getitem__(storage, "root"), node.get("schema")
                        )
                    return
                inspect_schema(current, node.get("schema"))
                return
            if node_type == "model-fields":
                if not isinstance(current, BaseModel):
                    return
                storage = object.__getattribute__(current, "__dict__")
                for name, field in node.get("fields", {}).items():
                    if dict.__contains__(storage, name):
                        inspect_schema(dict.__getitem__(storage, name), field)
                return
            if node_type == "model-field" or node_type == "typed-dict-field":
                inspect_schema(current, node.get("schema"))
                return
            if node_type == "typed-dict":
                if not isinstance(current, dict):
                    return
                fields = node.get("fields", {})
                field_names = set(fields)
                emitted_names = {
                    field.get("serialization_alias", name)
                    for name, field in fields.items()
                    if not field.get("serialization_exclude")
                }
                pairs = tuple(
                    zip(dict.__iter__(current), dict.values(current), strict=True)
                )
                string_values = {key: item for key, item in pairs if type(key) is str}
                required = {
                    name
                    for name, field in fields.items()
                    if field.get("required", True)
                }
                if not required.issubset(string_values):
                    return
                extras = set(string_values).difference(field_names)
                shadowed = emitted_names.intersection(extras)
                if shadowed:
                    names = ", ".join(repr(name) for name in sorted(shadowed))
                    raise ValueError(
                        f"output extras shadow declared serialized field keys: {names}"
                    )
                for name, field in fields.items():
                    if name in string_values:
                        inspect_schema(string_values[name], field)
                extras_schema = node.get("extras_schema")
                if extras_schema is not None:
                    for key, item in pairs:
                        if type(key) is not str or key in extras:
                            inspect_schema(item, extras_schema)
                return
            if node_type == "dataclass":
                cls = node.get("cls")
                if not isinstance(cls, type) or not any(
                    base is cls for base in type(current).__mro__
                ):
                    return
                inspect_schema(current, node.get("schema"))
                return
            if node_type == "dataclass-args":
                storages = dataclass_storage(current)
                for field in node.get("fields", ()):
                    name = field.get("name")
                    for storage in storages:
                        if dict.__contains__(storage, name):
                            inspect_schema(dict.__getitem__(storage, name), field)
                            break
                return
            if node_type == "dataclass-field":
                inspect_schema(current, node.get("schema"))
                return
            if node_type == "tagged-union":
                selected = tagged_union_choice(current, node)
                if selected is _missing:
                    raise ValueError(
                        "output tagged union discriminator cannot be read safely "
                        "from exact built-in or model storage"
                    )
                if schema_match_score(current, selected) is None:
                    raise ValueError(
                        "output tagged union storage is incompatible with its "
                        "selected discriminator branch"
                    )
                inspect_schema(current, selected)
                return
            if node_type == "union":
                choices = node.get("choices", ())
                values = choices.values() if isinstance(choices, dict) else choices
                candidates = [
                    choice[0] if isinstance(choice, tuple) else choice
                    for choice in values
                ]
                scored = [
                    (score, index, candidate)
                    for index, candidate in enumerate(candidates)
                    if (score := schema_match_score(current, candidate)) is not None
                ]
                if scored:
                    # Pydantic's smart unions prefer exact runtime evidence and use
                    # declaration order when branches remain indistinguishable. Audit
                    # only that conservative winner: applying every compatible branch
                    # can impose contradictory child-container schemas on valid output.
                    _, _, candidate = max(scored, key=lambda item: (item[0], -item[1]))
                    inspect_schema(current, candidate)
                    return
                container_choices = [
                    expected
                    for candidate in candidates
                    if (expected := declared_container_type(candidate)) is not None
                ]
                if container_choices:
                    raise ValueError(
                        "output container storage is incompatible with the declared "
                        f"built-in {container_choices[0].__name__} type"
                    )
                return

            if node_type == "json-or-python":
                inspect_schema(current, node.get("python_schema"))
                inspect_schema(current, node.get("json_schema"))
                return
            if node_type == "chain":
                steps = node.get("steps", ())
                if steps:
                    inspect_schema(current, steps[-1])

        inspect_schema(value, schema)

    def reject(value: Any) -> Any:
        seen: set[int] = set()

        def inspect(current: Any) -> None:
            current_type = type(current)
            for dataclass_type, field_names in dataclass_fields:
                if current_type is not dataclass_type:
                    continue
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                storages = dataclass_storage(current)
                for name in field_names:
                    for storage in storages:
                        if name in storage:
                            inspect(dict.__getitem__(storage, name))
                            break
                return

            if isinstance(current, BaseModel):
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                model_type = type(current)
                emitted = {
                    field.serialization_alias
                    if field.serialization_alias is not None
                    else name
                    for name, field in model_type.model_fields.items()
                    if not field.exclude
                }
                emitted.update(
                    field.alias if field.alias is not None else name
                    for name, field in model_type.model_computed_fields.items()
                )
                extras = object.__getattribute__(current, "__pydantic_extra__") or {}
                extra_names = {key for key in dict.__iter__(extras) if type(key) is str}
                shadowed = (set(model_type.model_fields) | emitted).intersection(
                    extra_names
                )
                if shadowed:
                    names = ", ".join(repr(name) for name in sorted(shadowed))
                    raise ValueError(
                        f"output extras shadow declared serialized field keys: {names}"
                    )
                storage = object.__getattribute__(current, "__dict__")
                for item in dict.values(storage):
                    inspect(item)
                for item in dict.values(extras):
                    inspect(item)
            elif isinstance(current, dict):
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                namespaces = _mapping_namespaces.get()
                namespace = None if namespaces is None else namespaces.get(identity)
                if namespace is not None and namespace[0] is current:
                    _, field_names, emitted_names = namespace
                    extras = {
                        key
                        for key in dict.__iter__(current)
                        if type(key) is str and key not in field_names
                    }
                    shadowed = emitted_names.intersection(extras)
                    if shadowed:
                        names = ", ".join(repr(name) for name in sorted(shadowed))
                        raise ValueError(
                            "output extras shadow declared serialized field keys: "
                            f"{names}"
                        )
                for item in dict.values(current):
                    inspect(item)
            elif type(current) is deque:
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                for item in deque.__iter__(current):
                    inspect(item)
            elif isinstance(current, deque):
                raise ValueError(
                    "output deque storage must use the exact collections.deque type"
                )
            elif isinstance(current, list):
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                for item in list.__iter__(current):
                    inspect(item)
            elif isinstance(current, tuple):
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                for item in tuple.__iter__(current):
                    inspect(item)
            elif isinstance(current, set):
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                for item in set.__iter__(current):
                    inspect(item)
            elif isinstance(current, frozenset):
                identity = id(current)
                if identity in seen:
                    return
                seen.add(identity)
                for item in frozenset.__iter__(current):
                    inspect(item)

        inspect(value)
        schema_audit(value)
        return value

    return reject


def _separate_typed_dict_extras(schema: dict[str, Any]) -> dict[str, Any]:
    """Reject extras that would duplicate declared TypedDict output keys."""
    fields = schema.get("fields", {})
    field_names = set(fields)
    emitted_names = {
        field.get("serialization_alias", name)
        for name, field in fields.items()
        if not field.get("serialization_exclude")
    }

    def reject(value: Any) -> Any:
        if isinstance(value, dict):
            extras = set(dict.__iter__(value)).difference(field_names)
            shadowed = emitted_names.intersection(extras)
            if shadowed:
                names = ", ".join(repr(name) for name in sorted(shadowed))
                raise ValueError(
                    f"output extras shadow declared serialized field keys: {names}"
                )
            namespaces = _mapping_namespaces.get()
            if namespaces is not None:
                namespaces[id(value)] = (
                    value,
                    frozenset(field_names),
                    frozenset(emitted_names),
                )
        return value

    return cast(
        dict[str, Any],
        core_schema.no_info_after_validator_function(
            reject, cast(core_schema.CoreSchema, schema)
        ),
    )


def _revalidating_schema(node: Any) -> Any:
    """Copy schema containers, retaining classes, hooks and definition references.

    Model instances hold canonical field names; mappings must retain their
    declared alias policy, even when nested inside a constructed instance.
    Branch locally at each model node rather than overriding validation flags
    globally. Any schemas deliberately remain Any: do not traverse runtime data.
    """
    if isinstance(node, dict):
        if node.get("type") == "model" and node.get("custom_init"):
            # Core invokes custom constructors even with _use_prebuilt=False.
            # A normal super().__init__ call then re-enters the original class
            # validator, bypassing our nested instance revalidation. Disabling
            # custom_init would silently discard mapping-input transformations;
            # reject the unsupported contract at registration instead.
            cls = node["cls"]
            raise TypeError(
                f"Output model {cls.__qualname__!r} uses a custom __init__, which "
                "is unsupported for runtime-enforced operation outputs; use "
                "model validators instead (including for nested models)."
            )
        is_schema = isinstance(node.get("type"), str)
        result = {
            key: value
            if is_schema and key in {"default", "metadata", "config", "serialization"}
            else _revalidating_schema(value)
            for key, value in node.items()
        }
        if (
            node.get("type") == "typed-dict"
            and result.get("config", {}).get("extra_fields_behavior") == "allow"
        ):
            return _separate_typed_dict_extras(result)
        if (
            node.get("type") not in ("model", "dataclass")
            or "cls" not in node
            or "schema" not in node
        ):
            return result
        result["revalidate_instances"] = "always"
        config = {**result.get("config", {}), "revalidate_instances": "always"}
        result["config"] = config
        reference = result.pop("ref", None)
        canonical = {
            **result,
            "config": {
                **config,
                "validate_by_alias": False,
                "validate_by_name": True,
            },
        }
        if (
            node.get("type") == "model"
            and config.get("extra_fields_behavior") == "allow"
        ):
            canonical = _separate_model_extras(canonical)
            result = _separate_model_extras(result)
        branch: dict[str, Any] = {
            "type": "tagged-union",
            "choices": {"instance": canonical, "input": result},
            "discriminator": _input_kind,
        }
        if reference is not None:
            branch["ref"] = reference
        return branch
    if isinstance(node, list):
        return [_revalidating_schema(value) for value in node]
    if isinstance(node, tuple):
        return tuple(_revalidating_schema(value) for value in node)
    return node


def _compile_output_validator(adapter: TypeAdapter[Any]) -> SchemaValidator:
    """Compile once at registration without modifying class-owned schemas."""
    _reject_ambiguous_object_namespaces(adapter.core_schema)
    _reject_callable_output_discriminators(adapter.core_schema)
    audit = _runtime_model_extra_collision_auditor(adapter.core_schema)

    def validate(value: Any, handler: Any) -> Any:
        token = _mapping_namespaces.set({})
        try:
            return audit(handler(value))
        finally:
            _mapping_namespaces.reset(token)

    schema = core_schema.no_info_wrap_validator_function(
        validate,
        cast(core_schema.CoreSchema, _revalidating_schema(adapter.core_schema)),
    )
    # REQUIRED: prebuilt class validators bypass our nested model branches and
    # revalidation policy. This private flag is covered by nested/recursive tests.
    return SchemaValidator(schema, _use_prebuilt=False)
