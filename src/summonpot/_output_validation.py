"""Compile private operation validators without serializing application values.

This relies on the tested Pydantic 2.13.5 / pydantic-core 2.46.5 schema
contract and the private ``_use_prebuilt`` compiler option. Dependency upgrades
must run the adversarial regression suite: allowing prebuilt validators silently
restores the model class's default (non-revalidating) instance behavior. Never
fall back to the original adapter if compilation fails.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import is_dataclass
from typing import Any, cast

from pydantic import BaseModel, TypeAdapter
from pydantic_core import SchemaValidator, core_schema


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
            for key, value in node.items():
                if key not in {"config", "default", "metadata", "serialization"}:
                    inspect(value, current_owner, current_config)
        elif isinstance(node, (list, tuple)):
            for value in node:
                inspect(value, owner, config)

    inspect(schema)


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
    schema = cast(core_schema.CoreSchema, _revalidating_schema(adapter.core_schema))
    # REQUIRED: prebuilt class validators bypass our nested model branches and
    # revalidation policy. This private flag is covered by nested/recursive tests.
    return SchemaValidator(schema, _use_prebuilt=False)
