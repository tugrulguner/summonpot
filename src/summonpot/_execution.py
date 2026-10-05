"""Private compiled execution contracts for endpoint operations."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import GetSetDescriptorType, MappingProxyType, MemberDescriptorType
from typing import Any, LiteralString
from uuid import UUID
from weakref import ReferenceType, ref

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticCustomError, SchemaValidator, TzInfo

from summonpot._output_validation import (
    _compile_input_validator,
    _compile_output_auditor,
    _compile_output_validator,
    _reject_ambiguous_object_namespaces,
)
from summonpot._validation import _enforced_contract_tool_index
from summonpot.contracts import AgentChoice, FromRequest
from summonpot.models import EndpointDef, ParamDef, ToolDef


class _RequestValues(dict[str, Any]):
    """JSON-safe prompt values plus canonical validated Python values."""

    __slots__ = ("typed",)

    def __init__(
        self,
        prompt: Mapping[str, Any],
        *,
        typed: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(prompt)
        self.typed = MappingProxyType(dict(prompt if typed is None else typed))


@dataclass(frozen=True, slots=True)
class _CompiledBinding:
    argument: str
    source: Any
    validator: _CompiledReceivingValidator | None


@dataclass(frozen=True, slots=True)
class _CompiledReceivingValidator:
    predicate: Callable[[Any, set[tuple[int, int]]], bool]

    def accepts(self, value: Any) -> bool:
        """Inspect the canonical value without transforming or copying it."""
        return self.predicate(value, set())


@dataclass(frozen=True, slots=True)
class _CompiledDefault:
    argument: str
    value: Any


@dataclass(frozen=True, slots=True)
class _CompiledParameter:
    name: str
    type_annotation: str
    description: str
    required: bool
    default: Any
    annotation: Any


@dataclass(frozen=True, slots=True)
class _ProjectionField:
    name: str
    prompt_name: str
    excluded: bool
    schema: _ProjectionSchema
    required: bool = False
    slot: MemberDescriptorType | None = None


@dataclass(frozen=True, slots=True)
class _ProjectionSchema:
    kind: str
    cls: type[Any] | None = None
    fields: tuple[_ProjectionField, ...] = ()
    item: _ProjectionSchema | None = None
    keys: _ProjectionSchema | None = None
    values: _ProjectionSchema | None = None
    extras: _ProjectionSchema | None = None
    choices: tuple[_ProjectionSchema, ...] = ()
    items: tuple[_ProjectionSchema, ...] = ()
    reference: str | None = None
    allow_extras: bool = False
    instance_dict: GetSetDescriptorType | None = None
    literal_values: tuple[Any, ...] = ()
    enum_members: tuple[tuple[Any, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class _CompiledTool:
    identity: int
    name: str
    description: str
    fn: Any
    signature: inspect.Signature
    annotations: Mapping[str, Any]
    required: bool
    minimum: int
    maximum: int | None
    bindings: tuple[_CompiledBinding, ...]
    defaults: tuple[_CompiledDefault, ...]
    output_adapter: TypeAdapter[Any] | None
    output_validator: SchemaValidator | None
    enforce_bound_exactly_once: bool

    @property
    def visible_signature(self) -> inspect.Signature:
        """Return the parameters the model is authorized to supply."""
        if not self.enforce_bound_exactly_once:
            return self.signature
        choices = {
            binding.argument
            for binding in self.bindings
            if isinstance(binding.source, AgentChoice)
        }
        return self.signature.replace(
            parameters=[
                parameter
                for name, parameter in self.signature.parameters.items()
                if name in choices
            ]
        )


@dataclass(frozen=True, slots=True)
class _CompiledEndpoint:
    path: str
    name: str
    description: str
    return_type: str
    parameters: tuple[_CompiledParameter, ...]
    input_model: Any
    input_adapter: TypeAdapter[Any]
    input_field_names: Mapping[str, str] | None
    input_validator: SchemaValidator
    prompt_schema: _ProjectionSchema
    prompt_definitions: Mapping[str, _ProjectionSchema]
    output_model: Any
    output_auditor: Callable[[Any], Any] | None
    model: str | None
    method: str
    operation_id: str
    path_parameter_names: tuple[str, ...]
    tools: tuple[_CompiledTool, ...]
    direct_tool: int | None


_REGISTERED_PLANS: dict[int, tuple[ReferenceType[EndpointDef], _CompiledEndpoint]] = {}


class _TransportRequest(_RequestValues):
    """Transport envelope; its mutable public views confer no validation authority."""

    __slots__ = ("__weakref__",)


@dataclass(frozen=True, slots=True)
class _TransportSnapshot:
    reference: ReferenceType[_TransportRequest]
    plan: _CompiledEndpoint
    prompt: dict[str, Any]
    typed: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ConsumedTransport:
    reference: ReferenceType[_TransportRequest]


_TRANSPORT_SNAPSHOTS: dict[int, _TransportSnapshot | _ConsumedTransport] = {}
_UNAVAILABLE = "<unavailable>"
_MISSING = object()
_BASE_MODEL_DICT_DESCRIPTOR = BaseModel.__dict__["__dict__"]
_BASE_MODEL_EXTRA_DESCRIPTOR = BaseModel.__dict__["__pydantic_extra__"]


def _pydantic_fields(value: BaseModel) -> dict[str, Any]:
    """Read Pydantic's field table without dispatching the model metaclass."""
    return type.__getattribute__(type(value), "__pydantic_fields__")


def _prompt_field_name(name: str, field: Any) -> str:
    """Read one declared prompt name directly from Pydantic field metadata."""
    serialization_alias = object.__getattribute__(field, "serialization_alias")
    if serialization_alias is not None:
        return serialization_alias
    alias = object.__getattribute__(field, "alias")
    return alias if alias is not None else name


def _field_is_statically_excluded(field: Any) -> bool:
    """Read static Field(exclude=True) metadata without application dispatch."""
    return object.__getattribute__(field, "exclude") is True


def _compile_projection_contract(
    source: Any,
) -> tuple[_ProjectionSchema, Mapping[str, _ProjectionSchema]]:
    """Snapshot the structural serialization boundary from Pydantic's schema."""
    definitions: dict[str, _ProjectionSchema] = {}
    root = source
    if source.get("type") == "definitions":
        root = source["schema"]
        for definition in source["definitions"]:
            reference = definition.get("ref")
            if type(reference) is str:
                definitions[reference] = _compile_projection_schema(definition)
    return _compile_projection_schema(root), MappingProxyType(definitions)


def _trusted_dataclass_descriptor(cls: Any, name: str) -> Any:
    """Find built-in storage descriptors without application attribute dispatch."""
    if not isinstance(cls, type):
        return None
    for base in type.__getattribute__(cls, "__mro__"):
        namespace = type.__getattribute__(base, "__dict__")
        descriptor = namespace.get(name)
        if type(descriptor) in (GetSetDescriptorType, MemberDescriptorType):
            return descriptor
    return None


def _compile_projection_schema(source: Any) -> _ProjectionSchema:
    """Retain only inert structure needed for model-facing prompt projection."""
    if type(source) is not dict or type(source.get("type")) is not str:
        return _ProjectionSchema("any")
    kind = source["type"]
    if kind == "definition-ref":
        reference = source.get("schema_ref")
        return _ProjectionSchema(
            "ref", reference=reference if type(reference) is str else None
        )
    if kind == "model":
        if source.get("root_model") is True:
            return _ProjectionSchema(
                "root-model",
                cls=source.get("cls"),
                item=_compile_projection_schema(source.get("schema")),
            )
        fields_schema = source.get("schema")
        while (
            type(fields_schema) is dict and fields_schema.get("type") != "model-fields"
        ):
            fields_schema = fields_schema.get("schema")
        fields: list[_ProjectionField] = []
        if type(fields_schema) is dict and type(fields_schema.get("fields")) is dict:
            for name, field_schema in fields_schema["fields"].items():
                if type(name) is not str or type(field_schema) is not dict:
                    continue
                alias = field_schema.get("serialization_alias", name)
                fields.append(
                    _ProjectionField(
                        name=name,
                        prompt_name=alias if type(alias) is str else name,
                        excluded=field_schema.get("serialization_exclude") is True,
                        schema=_compile_projection_schema(field_schema.get("schema")),
                    )
                )
        config = source.get("config")
        return _ProjectionSchema(
            "model",
            cls=source.get("cls"),
            fields=tuple(fields),
            allow_extras=(
                type(config) is dict and config.get("extra_fields_behavior") == "allow"
            ),
            extras=(
                _compile_projection_schema(fields_schema.get("extras_schema"))
                if type(fields_schema) is dict
                and fields_schema.get("extras_schema") is not None
                else None
            ),
        )
    if kind == "dataclass":
        cls = source.get("cls")
        fields_schema = source.get("schema")
        while (
            type(fields_schema) is dict
            and fields_schema.get("type") != "dataclass-args"
        ):
            fields_schema = fields_schema.get("schema")
        instance_dict = _trusted_dataclass_descriptor(cls, "__dict__")
        fields: list[_ProjectionField] = []
        if type(fields_schema) is dict and type(fields_schema.get("fields")) is list:
            for field_schema in fields_schema["fields"]:
                if type(field_schema) is not dict:
                    continue
                name = field_schema.get("name")
                if type(name) is not str:
                    continue
                alias = field_schema.get("serialization_alias", name)
                descriptor = _trusted_dataclass_descriptor(cls, name)
                fields.append(
                    _ProjectionField(
                        name=name,
                        prompt_name=alias if type(alias) is str else name,
                        excluded=field_schema.get("serialization_exclude") is True,
                        schema=_compile_projection_schema(field_schema.get("schema")),
                        slot=(
                            descriptor
                            if type(descriptor) is MemberDescriptorType
                            else None
                        ),
                    )
                )
        return _ProjectionSchema(
            "dataclass",
            cls=cls if isinstance(cls, type) else None,
            fields=tuple(fields),
            instance_dict=(
                instance_dict if type(instance_dict) is GetSetDescriptorType else None
            ),
        )
    if kind == "typed-dict":
        fields: list[_ProjectionField] = []
        source_fields = source.get("fields")
        if type(source_fields) is dict:
            for name, field_schema in source_fields.items():
                if type(name) is not str or type(field_schema) is not dict:
                    continue
                alias = field_schema.get("serialization_alias", name)
                fields.append(
                    _ProjectionField(
                        name=name,
                        prompt_name=alias if type(alias) is str else name,
                        excluded=field_schema.get("serialization_exclude") is True,
                        schema=_compile_projection_schema(field_schema.get("schema")),
                        required=field_schema.get("required") is True,
                    )
                )
        config = source.get("config")
        allow_extras = source.get("extra_behavior") == "allow" or (
            type(config) is dict and config.get("extra_fields_behavior") == "allow"
        )
        extras_schema = source.get("extras_schema")
        return _ProjectionSchema(
            "typed-dict",
            fields=tuple(fields),
            allow_extras=allow_extras,
            extras=(
                _compile_projection_schema(extras_schema)
                if extras_schema is not None
                else _ProjectionSchema("any")
            ),
        )
    if kind in ("list", "set", "frozenset", "generator"):
        return _ProjectionSchema(
            kind, item=_compile_projection_schema(source.get("items_schema"))
        )
    if kind == "dict":
        return _ProjectionSchema(
            kind,
            keys=_compile_projection_schema(source.get("keys_schema")),
            values=_compile_projection_schema(source.get("values_schema")),
        )
    if kind == "tuple":
        return _ProjectionSchema(
            kind,
            items=tuple(
                _compile_projection_schema(item)
                for item in source.get("items_schema", ())
            ),
        )
    if kind in ("union", "tagged-union"):
        raw_choices = source.get("choices", ())
        if type(raw_choices) is dict:
            raw_choices = tuple(raw_choices.values())
        return _ProjectionSchema(
            "union",
            choices=tuple(_compile_projection_schema(choice) for choice in raw_choices),
        )
    if kind == "nullable":
        return _ProjectionSchema(
            kind, item=_compile_projection_schema(source.get("schema"))
        )
    if kind == "literal":
        return _ProjectionSchema(kind, literal_values=tuple(source.get("expected", ())))
    if kind == "enum":
        members: list[tuple[Any, Any]] = []
        for member in source.get("members", ()):
            raw_value = object.__getattribute__(member, "_value_")
            if type(raw_value) in (type(None), bool, int, float, str, bytes):
                members.append((member, raw_value))
        return _ProjectionSchema(kind, enum_members=tuple(members))
    if kind in {
        "default",
        "function-before",
        "function-after",
        "function-wrap",
        "function-plain",
    }:
        return _compile_projection_schema(source.get("schema"))
    if kind in ("lax-or-strict", "json-or-python"):
        return _compile_projection_schema(
            source.get("python_schema", source.get("strict_schema"))
        )
    if kind == "chain":
        steps = source.get("steps", ())
        return _compile_projection_schema(steps[-1] if steps else None)
    return _ProjectionSchema(kind)


def _unsupported_raw_request(
    error_type: LiteralString, message: LiteralString
) -> ValidationError:
    """Build a stable admission error without rendering application-owned input."""
    error = PydanticCustomError(error_type, message)
    return ValidationError.from_exception_data(
        "request input",
        [{"type": error, "loc": (), "input": "<unsupported raw value>"}],
    )


def _inert_hashable(value: Any) -> bool:
    """Return whether a projected value can be hashed without application code."""
    kind = type(value)
    if kind in (
        type(None),
        bool,
        int,
        float,
        str,
        bytes,
        date,
        datetime,
        time,
        timedelta,
        Decimal,
        UUID,
    ):
        return True
    if kind is tuple or kind is frozenset:
        return all(_inert_hashable(item) for item in value)
    return False


def _inert_transport_value(
    value: Any,
    ancestors: frozenset[int] = frozenset(),
    *,
    native: bool = False,
    schema: _ProjectionSchema | None = None,
    definitions: Mapping[str, _ProjectionSchema] = MappingProxyType({}),
) -> Any:
    """Project known exact types only, without application serialization hooks."""
    if schema is not None:
        schema = _resolve_projection_wrappers(value, schema, definitions)
        if schema is None:
            raise _unsupported_raw_request(
                "request_projection",
                "request value does not match a safely projectable declared union branch",
            )
        if schema.kind == "nullable" and value is None:
            return None
        if schema.kind == "enum":
            for member, projected in schema.enum_members:
                if value is member:
                    return _inert_transport_value(
                        projected,
                        ancestors,
                        native=native,
                        definitions=definitions,
                    )
            return _UNAVAILABLE
    kind = type(value)
    if kind is UUID and type(value.int) is int and 0 <= value.int < 1 << 128:
        # UUID can be changed through object.__setattr__, so never share it.
        detached = UUID(int=value.int)
        return detached if native else str(detached)
    if kind is bytes or kind is date or kind is timedelta or kind is Decimal:
        # Exact immutable native values contain no application-owned graph.
        return value if native else str(value)
    if kind is datetime or kind is time:
        tz = value.tzinfo
        if tz is None or type(tz) is timezone or type(tz) is TzInfo:
            # These fixed-offset zones have no application callbacks. Unknown
            # tzinfo implementations must not be asked for offsets or names.
            detached_datetime = value.replace()
            return detached_datetime if native else str(detached_datetime)
        return _UNAVAILABLE
    if kind is type(None) or kind is bool or kind is int or kind is str:
        return value
    if kind is float:
        return value if math.isfinite(value) else _UNAVAILABLE
    if schema is not None and schema.kind == "dataclass":
        if (
            schema.cls is None
            or id(value) in ancestors
            or len(ancestors) >= 64
            or not any(
                base is schema.cls for base in type.__getattribute__(kind, "__mro__")
            )
        ):
            return _UNAVAILABLE
        storage: Any = None
        if schema.instance_dict is not None:
            storage = GetSetDescriptorType.__get__(schema.instance_dict, value, kind)
            if type(storage) is not dict or not _has_exact_string_keys(storage):
                return _UNAVAILABLE
        ancestors = ancestors | {id(value)}
        projected: dict[str, Any] = {}
        for projection_field in schema.fields:
            if projection_field.excluded:
                continue
            item = _MISSING
            if type(storage) is dict and dict.__contains__(
                storage, projection_field.name
            ):
                item = dict.__getitem__(storage, projection_field.name)
            elif projection_field.slot is not None:
                with suppress(AttributeError):
                    item = MemberDescriptorType.__get__(
                        projection_field.slot, value, kind
                    )
            if item is not _MISSING:
                projected[projection_field.prompt_name] = _inert_transport_value(
                    item,
                    ancestors,
                    native=native,
                    schema=projection_field.schema,
                    definitions=definitions,
                )
        return projected
    if _class_is_in_mro(value, BaseModel):
        if id(value) in ancestors or len(ancestors) >= 64:
            return _UNAVAILABLE
        ancestors = ancestors | {id(value)}
        # Read Pydantic's storage directly: model_dump, getattr, repr, copy and
        # equality can all dispatch application code.  Declared aliases and
        # exact built-in descendants are enough for the model-facing view.
        storage = _BASE_MODEL_DICT_DESCRIPTOR.__get__(value, kind)
        if type(storage) is not dict or not _has_exact_string_keys(storage):
            return _UNAVAILABLE
        if schema is not None and schema.kind == "root-model":
            if schema.item is None or not dict.__contains__(storage, "root"):
                return _UNAVAILABLE
            return _inert_transport_value(
                dict.__getitem__(storage, "root"),
                ancestors,
                native=native,
                schema=schema.item,
                definitions=definitions,
            )
        if schema is not None and schema.kind == "model":
            projected = {
                field.prompt_name: _inert_transport_value(
                    dict.__getitem__(storage, field.name),
                    ancestors,
                    native=native,
                    schema=field.schema,
                    definitions=definitions,
                )
                for field in schema.fields
                if dict.__contains__(storage, field.name) and not field.excluded
            }
        else:
            projected = {
                _prompt_field_name(name, field): _inert_transport_value(
                    dict.__getitem__(storage, name), ancestors, native=native
                )
                for name, field in _pydantic_fields(value).items()
                if dict.__contains__(storage, name)
                and not _field_is_statically_excluded(field)
            }
        extras = _base_model_extra(value, storage)
        if extras is not None and (
            type(extras) is not dict or not _has_exact_string_keys(extras)
        ):
            return _UNAVAILABLE
        if type(extras) is dict and (schema is None or schema.allow_extras):
            projected.update(
                {
                    key: _inert_transport_value(
                        item,
                        ancestors,
                        native=native,
                        schema=schema.extras if schema is not None else None,
                        definitions=definitions,
                    )
                    for key, item in extras.items()
                    if type(key) is str and key not in projected
                }
            )
        return projected
    if (
        (
            kind is not dict
            and kind is not list
            and kind is not tuple
            and kind is not set
            and kind is not frozenset
        )
        or id(value) in ancestors
        or len(ancestors) >= 64
    ):
        return _UNAVAILABLE
    ancestors = ancestors | {id(value)}
    if kind is dict:
        # Do not stringify keys: even hashing an application key can execute code.
        if schema is not None and schema.kind == "typed-dict":
            if not _has_exact_string_keys(value):
                return _UNAVAILABLE
            projected = {
                field.prompt_name: _inert_transport_value(
                    dict.__getitem__(value, field.name),
                    ancestors,
                    native=native,
                    schema=field.schema,
                    definitions=definitions,
                )
                for field in schema.fields
                if dict.__contains__(value, field.name) and not field.excluded
            }
            if schema.allow_extras:
                declared_names = {field.name for field in schema.fields}
                for key, item in dict.items(value):
                    if key in declared_names or key in projected:
                        continue
                    projected[key] = _inert_transport_value(
                        item,
                        ancestors,
                        native=native,
                        schema=schema.extras,
                        definitions=definitions,
                    )
            return projected
        value_schema = (
            schema.values if schema is not None and schema.kind == "dict" else None
        )
        return {
            key: _inert_transport_value(
                item,
                ancestors,
                native=native,
                schema=value_schema,
                definitions=definitions,
            )
            for key, item in value.items()
            if type(key) is str
        }
    if schema is not None and schema.kind == "tuple" and schema.items:
        item_schemas: tuple[_ProjectionSchema | None, ...] = tuple(
            schema.items[min(index, len(schema.items) - 1)]
            for index in range(len(value))
        )
    else:
        item_schema = (
            schema.item
            if schema is not None
            and schema.kind in ("list", "set", "frozenset", "generator")
            else None
        )
        item_schemas = (item_schema,) * len(value)
    items = [
        _inert_transport_value(
            item,
            ancestors,
            native=native,
            schema=item_schemas[index],
            definitions=definitions,
        )
        for index, item in enumerate(value)
    ]
    if native and kind in (set, frozenset):
        if not all(_inert_hashable(item) for item in items):
            return _UNAVAILABLE
        return kind(items)
    return kind(items) if native else items


def _resolve_projection_wrappers(
    value: Any,
    schema: _ProjectionSchema,
    definitions: Mapping[str, _ProjectionSchema],
) -> _ProjectionSchema | None:
    """Resolve refs, nullable wrappers, and selected unions to a renderable schema."""
    seen_references: set[str] = set()
    while True:
        if schema.kind == "ref":
            reference = schema.reference
            if (
                reference is None
                or reference in seen_references
                or reference not in definitions
            ):
                return schema
            seen_references.add(reference)
            schema = definitions[reference]
            continue
        if schema.kind == "nullable" and value is not None:
            if schema.item is None:
                return None
            schema = schema.item
            continue
        if schema.kind == "union":
            selected = _projection_union_choice(value, schema.choices, definitions)
            if selected is None:
                return None
            schema = selected
            continue
        return schema


def _projection_schema_applies(
    value: Any,
    schema: _ProjectionSchema,
    definitions: Mapping[str, _ProjectionSchema],
    depth: int = 0,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    """Match a value to a declared branch without application dispatch."""
    marker = (id(value), id(schema))
    if depth >= 64 or marker in seen:
        # Rendering has the same bound and replaces the uninspected tail with an
        # inert sentinel, so applicability may conservatively retain this branch.
        return True
    seen = seen | {marker}
    while (
        schema.kind == "ref"
        and schema.reference is not None
        and schema.reference in definitions
    ):
        schema = definitions[schema.reference]
    if schema.kind == "nullable":
        return value is None or (
            schema.item is not None
            and _projection_schema_applies(value, schema.item, definitions, depth, seen)
        )
    if schema.kind == "union":
        return any(
            _projection_schema_applies(value, choice, definitions, depth, seen)
            for choice in schema.choices
        )
    if schema.kind == "any":
        return True
    if schema.kind == "literal":
        return any(
            value is expected
            or (
                type(value) in _LITERAL_TYPES
                and type(value) is type(expected)
                and value == expected
            )
            for expected in schema.literal_values
        )
    if schema.kind == "enum":
        return any(value is member for member, _ in schema.enum_members)

    kind = type(value)
    runtime_mro = type.__getattribute__(kind, "__mro__")
    if schema.kind in ("model", "root-model", "dataclass"):
        return schema.cls is not None and any(
            base is schema.cls for base in runtime_mro
        )

    expected = {
        "none": type(None),
        "bool": bool,
        "int": int,
        "float": float,
        "str": str,
        "bytes": bytes,
        "date": date,
        "datetime": datetime,
        "time": time,
        "timedelta": timedelta,
        "decimal": Decimal,
        "uuid": UUID,
    }
    if schema.kind in expected:
        return expected[schema.kind] is kind
    if schema.kind in ("list", "set", "frozenset"):
        expected_kind = {
            "list": list,
            "set": set,
            "frozenset": frozenset,
        }[schema.kind]
        return (
            kind is expected_kind
            and schema.item is not None
            and all(
                _projection_schema_applies(
                    item, schema.item, definitions, depth + 1, seen
                )
                for item in value
            )
        )
    if schema.kind == "tuple":
        if kind is not tuple or not schema.items:
            return False
        return all(
            _projection_schema_applies(
                item,
                schema.items[min(index, len(schema.items) - 1)],
                definitions,
                depth + 1,
                seen,
            )
            for index, item in enumerate(value)
        )
    if schema.kind == "dict":
        return (
            kind is dict
            and schema.keys is not None
            and schema.values is not None
            and all(
                _projection_schema_applies(
                    key, schema.keys, definitions, depth + 1, seen
                )
                and _projection_schema_applies(
                    item, schema.values, definitions, depth + 1, seen
                )
                for key, item in value.items()
            )
        )
    if schema.kind == "typed-dict":
        if kind is not dict or not _has_exact_string_keys(value):
            return False
        if not all(
            not field.required or dict.__contains__(value, field.name)
            for field in schema.fields
        ) or not all(
            not dict.__contains__(value, field.name)
            or _projection_schema_applies(
                dict.__getitem__(value, field.name),
                field.schema,
                definitions,
                depth + 1,
                seen,
            )
            for field in schema.fields
        ):
            return False
        declared_names = {field.name for field in schema.fields}
        extras = [
            item for name, item in dict.items(value) if name not in declared_names
        ]
        return not extras or (
            schema.allow_extras
            and schema.extras is not None
            and all(
                _projection_schema_applies(
                    item, schema.extras, definitions, depth + 1, seen
                )
                for item in extras
            )
        )
    return False


def _projection_union_choice(
    value: Any,
    choices: tuple[_ProjectionSchema, ...],
    definitions: Mapping[str, _ProjectionSchema],
) -> _ProjectionSchema | None:
    """Choose a declared union branch from canonical runtime types only."""
    resolved: list[_ProjectionSchema] = []
    for choice in choices:
        while (
            choice.kind == "ref"
            and choice.reference is not None
            and choice.reference in definitions
        ):
            choice = definitions[choice.reference]
        resolved.append(choice)
    kind = type(value)
    runtime_mro = type.__getattribute__(kind, "__mro__")
    if any(base is BaseModel for base in runtime_mro):
        for exact in (True, False):
            for choice in resolved:
                if choice.kind not in ("model", "root-model") or choice.cls is None:
                    continue
                matches = (
                    kind is choice.cls
                    if exact
                    else any(base is choice.cls for base in runtime_mro)
                )
                if matches:
                    return choice
    for exact in (True, False):
        for choice in resolved:
            if choice.kind != "dataclass" or choice.cls is None:
                continue
            matches = (
                kind is choice.cls
                if exact
                else any(base is choice.cls for base in runtime_mro)
            )
            if matches:
                return choice
    applicable = [
        choice
        for choice in resolved
        if choice.kind != "any"
        and _projection_schema_applies(value, choice, definitions)
    ]
    if applicable:
        # Pydantic resolves structurally indistinguishable branches left-to-right.
        # Empty containers are the common case: either applicable branch projects
        # the same inert value, so retaining declaration order preserves HTTP parity.
        return applicable[0]
    fallbacks = [choice for choice in resolved if choice.kind == "any"]
    return fallbacks[0] if len(fallbacks) == 1 else None


def _public_transport_views(
    plan: _CompiledEndpoint,
    prompt: Mapping[str, Any],
    typed: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return independent inert trees, not declared serializer representations."""
    return _inert_transport_value(prompt), _inert_transport_value(typed, native=True)


def _validated_transport_request(
    plan: _CompiledEndpoint,
    prompt: Mapping[str, Any],
    *,
    typed: Mapping[str, Any],
) -> _RequestValues:
    """Transfer FastAPI-validated values to this exact compiled route plan.

    Only the HTTP adapter calls this factory after validation. Neither an ordinary
    _RequestValues nor the envelope's mutable views is proof of validation. Keep
    the framework-owned source graphs private, and release them after one use.
    """
    # The envelope carries compatibility views for custom runtimes, but never the
    # authoritative graph. Its values are inert built-in projections;
    # only the private one-shot snapshot proves prior validation.
    public_prompt, public_typed = _public_transport_views(plan, prompt, typed)
    request = _TransportRequest(public_prompt, typed=public_typed)
    identity = id(request)

    def discard(reference: ReferenceType[_TransportRequest]) -> None:
        current = _TRANSPORT_SNAPSHOTS.get(identity)
        if current is not None and current.reference is reference:
            _TRANSPORT_SNAPSHOTS.pop(identity, None)

    _TRANSPORT_SNAPSHOTS[identity] = _TransportSnapshot(
        ref(request, discard), plan, _inert_transport_value(prompt), dict(typed)
    )
    return request


def _register_endpoint(
    endpoint: EndpointDef,
    *,
    allow_direct: bool = True,
) -> _CompiledEndpoint:
    """Compile and privately retain one endpoint's immutable execution plan."""
    plan = _compile_endpoint(endpoint, allow_direct=allow_direct)
    identity = id(endpoint)

    def discard(reference: ReferenceType[EndpointDef]) -> None:
        current = _REGISTERED_PLANS.get(identity)
        if current is not None and current[0] is reference:
            _REGISTERED_PLANS.pop(identity, None)

    reference = ref(endpoint, discard)
    _REGISTERED_PLANS[identity] = (reference, plan)
    return plan


def _registered_plan(endpoint: EndpointDef) -> _CompiledEndpoint | None:
    """Return only the plan registered for this exact endpoint object."""
    current = _REGISTERED_PLANS.get(id(endpoint))
    if current is not None and current[0]() is endpoint:
        return current[1]
    return None


@dataclass(slots=True)
class _OperationState:
    started: int = 0
    running: int = 0
    succeeded: int = 0


@dataclass(slots=True)
class _EndpointRun:
    """Mutable state owned by exactly one endpoint invocation."""

    request: Mapping[str, Any]
    states: list[_OperationState]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _compile_endpoint(
    endpoint: EndpointDef,
    *,
    allow_direct: bool = True,
) -> _CompiledEndpoint:
    """Snapshot validated endpoint metadata into an immutable runtime plan."""
    source_tools = tuple(endpoint.tools)
    output_adapter = (
        TypeAdapter(endpoint.output_model)
        if endpoint.output_model is not None
        else None
    )
    output_shapes = [
        *(
            tool.contract.output
            for tool in source_tools
            if tool.contract is not None and tool.contract.output is not None
        ),
    ]
    for output in output_shapes:
        if output is not None:
            _reject_ambiguous_object_namespaces(TypeAdapter(output).core_schema)
    enforce_index = _enforced_contract_tool_index(source_tools)
    direct_index = (
        _direct_tool_index(endpoint, source_tools, enforce_index)
        if allow_direct
        else None
    )
    tools = tuple(
        _compile_tool(
            tool,
            index,
            enforce=index == enforce_index,
            snapshot_defaults=index == direct_index,
        )
        for index, tool in enumerate(source_tools)
    )
    input_adapter, input_field_names = _compile_input_adapter(endpoint)
    prompt_schema, prompt_definitions = _compile_projection_contract(
        input_adapter.core_schema
    )
    return _CompiledEndpoint(
        path=endpoint.path,
        name=endpoint.name,
        description=endpoint.description,
        return_type=endpoint.return_type,
        parameters=tuple(_compile_parameter(param) for param in endpoint.parameters),
        input_model=endpoint.input_model,
        input_adapter=input_adapter,
        input_field_names=input_field_names,
        input_validator=_compile_input_validator(input_adapter),
        prompt_schema=prompt_schema,
        prompt_definitions=prompt_definitions,
        output_model=endpoint.output_model,
        output_auditor=(
            _compile_output_auditor(output_adapter)
            if output_adapter is not None
            else None
        ),
        model=endpoint.model,
        method=endpoint.method,
        operation_id=endpoint.operation_id,
        path_parameter_names=tuple(endpoint.path_parameter_names),
        tools=tools,
        direct_tool=direct_index,
    )


def _compile_input_adapter(
    endpoint: EndpointDef,
) -> tuple[TypeAdapter[Any], Mapping[str, str] | None]:
    """Compile the request contract used by raw runtime callers."""
    if endpoint.input_model is not None:
        return TypeAdapter(endpoint.input_model), None
    if not endpoint.parameters:
        empty_model = create_model(
            f"{endpoint.name}RuntimeRequest",
            __config__=ConfigDict(extra="forbid"),
        )
        return TypeAdapter(empty_model), MappingProxyType({})
    request_model, field_names = _create_parameter_model(
        f"{endpoint.name}RuntimeRequest",
        [
            (
                parameter.name,
                parameter.annotation
                if parameter.annotation is not None
                and not isinstance(parameter.annotation, str)
                else Any,
                parameter.required,
                parameter.default,
            )
            for parameter in endpoint.parameters
        ],
    )
    return TypeAdapter(request_model), field_names


def _create_parameter_model(
    model_name: str,
    parameters: Sequence[tuple[str, Any, bool, Any]],
    *,
    all_parameter_names: Sequence[str] | None = None,
) -> tuple[type[BaseModel], Mapping[str, str]]:
    """Create an aliased model without exposing public names to model internals."""
    fields: dict[str, tuple[Any, Any]] = {}
    field_names: dict[str, str] = {}
    public_names = (
        tuple(all_parameter_names)
        if all_parameter_names is not None
        else tuple(name for name, *_ in parameters)
    )
    public_name_set = set(public_names)
    internal_names: dict[str, str] = {}
    occupied: set[str] = set()
    for index, name in enumerate(public_names):
        reserved = (
            name.startswith("_")
            or name in inspect.signature(create_model).parameters
            or any(
                name in type.__getattribute__(base, "__dict__")
                for base in type.__getattribute__(BaseModel, "__mro__")
            )
        )
        internal_name = name
        if reserved:
            candidate_index = index
            internal_name = f"summonpot_field_{candidate_index}"
            while internal_name in public_name_set or internal_name in occupied:
                candidate_index += 1
                internal_name = f"summonpot_field_{candidate_index}"
        internal_names[name] = internal_name
        occupied.add(internal_name)

    for name, annotation, required, parameter_default in parameters:
        internal_name = internal_names[name]
        aliased = internal_name != name
        default = ... if required else parameter_default
        field = FieldInfo.from_annotated_attribute(
            annotation,
            default,  # pyright: ignore[reportArgumentType]
        )
        if aliased and field.validation_alias is None:
            field.validation_alias = name
        if aliased and field.serialization_alias is None:
            field.serialization_alias = name
        fields[internal_name] = (field.annotation or annotation, field)
        field_names[internal_name] = name
    request_model = create_model(
        model_name,
        **fields,  # pyright: ignore[reportArgumentType, reportCallIssue]
    )
    return request_model, MappingProxyType(field_names)


def _direct_tool_index(
    endpoint: EndpointDef,
    tools: Sequence[ToolDef],
    enforce_index: int | None,
) -> int | None:
    """Return the narrow operation that can execute without a model."""
    if enforce_index is None or endpoint.input_model is None:
        return None
    contract = tools[enforce_index].contract
    if contract is None or contract.output is not endpoint.output_model:
        return None
    if not contract.bind or any(
        not isinstance(source, FromRequest) for source in contract.bind.values()
    ):
        return None
    if not _direct_defaults_are_stable(tools[enforce_index], contract.bind):
        return None
    return enforce_index


def _direct_defaults_are_stable(tool: ToolDef, bindings: Mapping[str, Any]) -> bool:
    """Return whether every direct-path default is immutable and identity-stable."""
    signature, _ = _resolved_signature(tool.fn)
    for name, parameter in signature.parameters.items():
        if name in bindings or parameter.default is inspect.Parameter.empty:
            continue
        if not _is_immutable_default(parameter.default):
            return False
    return True


def _is_immutable_default(value: Any) -> bool:
    """Recognize only built-in immutable values, never user copy hooks."""
    if type(value) in (type(None), bool, int, float, complex, str, bytes):
        return True
    if type(value) in (tuple, frozenset):
        return all(_is_immutable_default(item) for item in value)
    return False


_ReceivingPredicate = Callable[[Any, set[tuple[int, int]]], bool]
_LITERAL_TYPES = (type(None), bool, int, float, str, bytes)
_BASE_MODEL_DICT_DESCRIPTOR = BaseModel.__dict__["__dict__"]
_BASE_MODEL_EXTRA_DESCRIPTOR = BaseModel.__dict__["__pydantic_extra__"]


def _class_is_in_mro(value: Any, expected: type[Any]) -> bool:
    """Perform an instance check without a custom metaclass __instancecheck__."""
    value_type = type(value)
    return any(
        base is expected for base in type.__getattribute__(value_type, "__mro__")
    )


def _base_model_extra(value: Any, values: dict[str, Any]) -> Any:
    """Read Pydantic extra storage without invoking subclass descriptors."""
    try:
        return type(_BASE_MODEL_EXTRA_DESCRIPTOR).__get__(
            _BASE_MODEL_EXTRA_DESCRIPTOR, value, type(value)
        )
    except AttributeError:
        for name, item in dict.items(values):
            if type(name) is str and name == "__pydantic_extra__":
                return item
        return None


def _has_exact_string_keys(value: dict[Any, Any]) -> bool:
    """Reject malformed model storage before any hash-based field lookup."""
    return all(type(name) is str for name in dict.__iter__(value))


def _length_ok(length: int, schema: Mapping[str, Any]) -> bool:
    minimum = schema.get("min_length")
    maximum = schema.get("max_length")
    return (minimum is None or length >= minimum) and (
        maximum is None or length <= maximum
    )


def _number_ok(
    value: Any, schema: Mapping[str, Any], model_config: Mapping[str, Any]
) -> bool:
    allow_inf_nan = schema.get("allow_inf_nan", model_config.get("allow_inf_nan"))
    if allow_inf_nan is False and type(value) in {float, Decimal}:
        finite = value.is_finite() if type(value) is Decimal else math.isfinite(value)
        if not finite:
            return False
    for key, operation in (
        ("gt", lambda left, right: left > right),
        ("ge", lambda left, right: left >= right),
        ("lt", lambda left, right: left < right),
        ("le", lambda left, right: left <= right),
    ):
        boundary = schema.get(key)
        if boundary is not None and not operation(value, boundary):
            return False
    multiple = schema.get("multiple_of")
    return multiple is None or value % multiple == 0


def _seen_before(value: Any, token: int, seen: set[tuple[int, int]]) -> bool:
    marker = (id(value), token)
    if marker in seen:
        return True
    seen.add(marker)
    return False


def _unsupported_receiver(message: str) -> TypeError:
    return TypeError(f"Unsupported receiving parameter contract: {message}.")


def _require_supported_schema_keys(
    schema: Mapping[str, Any], allowed: set[str]
) -> None:
    bookkeeping = {"type", "strict", "ref", "metadata", "serialization"}
    unsupported = set(schema).difference(bookkeeping, allowed)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise _unsupported_receiver(f"constraints {names} are not supported")


def _receiving_model_config(node: Mapping[str, Any]) -> Mapping[str, Any]:
    config = node.get("config", {})
    if type(config) is not dict:
        raise _unsupported_receiver("invalid Pydantic model config")
    transforming = {
        name
        for name in (
            "str_strip_whitespace",
            "str_to_lower",
            "str_to_upper",
            "coerce_numbers_to_str",
        )
        if config.get(name) is True
    }
    if transforming:
        names = ", ".join(sorted(transforming))
        raise _unsupported_receiver(
            f"transforming model config options {names} are not hook-free"
        )
    return config


def _compile_receiving_schema(schema: Any) -> _ReceivingPredicate:
    """Compile the hook-free core-schema subset used for receiving checks."""
    definitions: dict[str, Any] = {}
    references: dict[str, _ReceivingPredicate] = {}

    def compile_node(
        node: Any, model_config: Mapping[str, Any] | None = None
    ) -> _ReceivingPredicate:
        if model_config is None:
            model_config = {}
        if type(node) is not dict or type(node.get("type")) is not str:
            raise _unsupported_receiver("invalid Pydantic core schema")
        kind = node["type"]

        if kind.startswith("function-"):
            raise _unsupported_receiver(
                "custom functional validators are not hook-free"
            )
        if kind == "definitions":
            for definition in node.get("definitions", ()):
                reference = definition.get("ref")
                if type(reference) is str:
                    definitions[reference] = definition
            return compile_node(node["schema"], model_config)
        if kind == "definition-ref":
            reference = node["schema_ref"]
            existing = references.get(reference)
            if existing is not None:
                return existing
            holder: list[_ReceivingPredicate] = []

            def deferred(value: Any, seen: set[tuple[int, int]]) -> bool:
                return holder[0](value, seen)

            references[reference] = deferred
            target = definitions.get(reference)
            if target is None:
                raise _unsupported_receiver("unresolved recursive schema reference")
            holder.append(compile_node(target, model_config))
            return deferred
        if kind in {"default", "nullable", "custom-error"}:
            child = compile_node(node["schema"], model_config)
            if kind == "nullable":
                return lambda value, seen: value is None or child(value, seen)
            return child
        if kind == "lax-or-strict":
            return compile_node(node["strict_schema"], model_config)
        if kind == "json-or-python":
            return compile_node(node["python_schema"], model_config)
        if kind == "any":
            return lambda value, seen: True
        if kind == "none":
            return lambda value, seen: value is None

        exact_types: dict[str, type[Any]] = {
            "bool": bool,
            "bytes": bytes,
            "complex": complex,
            "date": date,
            "datetime": datetime,
            "decimal": Decimal,
            "float": float,
            "int": int,
            "str": str,
            "time": time,
            "timedelta": timedelta,
            "uuid": UUID,
        }
        if kind in exact_types:
            expected = exact_types[kind]
            if kind == "float" and node.get("multiple_of") is not None:
                raise _unsupported_receiver(
                    "float multiple_of constraints are not supported"
                )
            allow_inf_nan = node.get("allow_inf_nan", model_config.get("allow_inf_nan"))
            if kind == "decimal" and allow_inf_nan is True:
                raise _unsupported_receiver(
                    "Decimal allow_inf_nan=True is not supported"
                )
            allowed_constraints = {
                "int": {"gt", "ge", "lt", "le", "multiple_of"},
                "float": {
                    "gt",
                    "ge",
                    "lt",
                    "le",
                    "multiple_of",
                    "allow_inf_nan",
                },
                "decimal": {
                    "gt",
                    "ge",
                    "lt",
                    "le",
                    "multiple_of",
                    "allow_inf_nan",
                },
                "str": {"min_length", "max_length", "pattern"},
                "bytes": {"min_length", "max_length"},
                # Parsing precision has no effect on an already-canonical object.
                "datetime": {"microseconds_precision"},
                "time": {"microseconds_precision"},
                "timedelta": {"microseconds_precision"},
                "uuid": {"version"},
            }
            _require_supported_schema_keys(node, allowed_constraints.get(kind, set()))
            if kind == "str" and node.get("pattern") is not None:
                raise _unsupported_receiver(
                    "string pattern constraints are not supported"
                )

            def scalar(value: Any, seen: set[tuple[int, int]]) -> bool:
                if type(value) is not expected:
                    return False
                if kind == "decimal" and not Decimal.is_finite(value):
                    return False
                if kind in {"int", "float", "decimal"} and not _number_ok(
                    value, node, model_config
                ):
                    return False
                length_schema = node
                if kind == "str":
                    length_schema = {
                        "min_length": node.get(
                            "min_length", model_config.get("str_min_length")
                        ),
                        "max_length": node.get(
                            "max_length", model_config.get("str_max_length")
                        ),
                    }
                if kind in {"str", "bytes"} and not _length_ok(
                    len(value), length_schema
                ):
                    return False
                version = node.get("version")
                return not (
                    kind == "uuid" and version is not None and value.version != version
                )

            return scalar
        if kind == "literal":
            expected_values = tuple(node.get("expected", ()))
            if any(type(item) not in _LITERAL_TYPES for item in expected_values):
                raise _unsupported_receiver(
                    "non-primitive Literal values are not hook-free"
                )

            def literal(value: Any, seen: set[tuple[int, int]]) -> bool:
                return any(
                    type(value) is type(expected)
                    and (value is expected or value == expected)
                    for expected in expected_values
                )

            return literal
        if kind in {"union", "tagged-union"}:
            if kind == "tagged-union" and callable(node.get("discriminator")):
                raise _unsupported_receiver("callable discriminators are not hook-free")
            raw_choices = (
                node.get("choices", ())
                if kind == "union"
                else tuple(node.get("choices", {}).values())
            )
            choices = tuple(
                compile_node(
                    choice[0] if type(choice) is tuple else choice, model_config
                )
                for choice in raw_choices
            )
            return lambda value, seen: any(
                choice(value, set(seen)) for choice in choices
            )
        if kind == "is-instance":
            expected_class = node["cls"]
            if type(expected_class) is not type:
                raise _unsupported_receiver(
                    "custom instance-checking metaclasses are not supported"
                )
            return lambda value, seen: _class_is_in_mro(value, expected_class)
        if kind == "enum":
            raise _unsupported_receiver("enum contracts are not supported")
        if kind in {"list", "set", "frozenset"}:
            expected_class = {"list": list, "set": set, "frozenset": frozenset}[kind]
            length = {
                "list": list.__len__,
                "set": set.__len__,
                "frozenset": frozenset.__len__,
            }[kind]
            iterator = {
                "list": list.__iter__,
                "set": set.__iter__,
                "frozenset": frozenset.__iter__,
            }[kind]
            child = compile_node(
                node.get("items_schema", {"type": "any"}), model_config
            )
            token = id(node)

            def collection(value: Any, seen: set[tuple[int, int]]) -> bool:
                if not _class_is_in_mro(value, expected_class):
                    return False
                if not _length_ok(length(value), node):
                    return False
                if _seen_before(value, token, seen):
                    return True
                return all(child(item, seen) for item in iterator(value))

            return collection
        if kind == "tuple":
            children = tuple(
                compile_node(item, model_config)
                for item in node.get("items_schema", ())
            )
            variadic = node.get("variadic_item_index")
            token = id(node)

            def tuple_value(value: Any, seen: set[tuple[int, int]]) -> bool:
                if not _class_is_in_mro(value, tuple) or not _length_ok(
                    tuple.__len__(value), node
                ):
                    return False
                if _seen_before(value, token, seen):
                    return True
                items = tuple.__iter__(value)
                if variadic is not None:
                    return all(children[variadic](item, seen) for item in items)
                if tuple.__len__(value) != len(children):
                    return False
                return all(
                    child(item, seen)
                    for child, item in zip(children, items, strict=True)
                )

            return tuple_value
        if kind == "dict":
            key_predicate = compile_node(
                node.get("keys_schema", {"type": "any"}), model_config
            )
            value_predicate = compile_node(
                node.get("values_schema", {"type": "any"}), model_config
            )
            token = id(node)

            def dictionary(value: Any, seen: set[tuple[int, int]]) -> bool:
                if not _class_is_in_mro(value, dict) or not _length_ok(
                    dict.__len__(value), node
                ):
                    return False
                if _seen_before(value, token, seen):
                    return True
                return all(
                    key_predicate(key, seen) and value_predicate(item, seen)
                    for key, item in dict.items(value)
                )

            return dictionary
        if kind == "model-field":
            return compile_node(node["schema"], model_config)
        if kind == "model-fields":
            fields = tuple(
                (name, compile_node(field_schema, model_config))
                for name, field_schema in node.get("fields", {}).items()
            )

            def model_fields(value: Any, seen: set[tuple[int, int]]) -> bool:
                if type(value) is not dict:
                    return False
                for name, predicate in fields:
                    if not dict.__contains__(value, name) or not predicate(
                        dict.__getitem__(value, name), seen
                    ):
                        return False
                return True

            return model_fields
        if kind == "model":
            if node.get("custom_init") or node.get("post_init") is not None:
                raise _unsupported_receiver(
                    "Pydantic model lifecycle hooks are not supported"
                )
            model_class = node["cls"]
            nested_config = _receiving_model_config(node)
            child = compile_node(node["schema"], nested_config)
            model_schema = node["schema"]
            extra_behavior = nested_config.get("extra_fields_behavior")
            extras_schema = (
                model_schema.get("extras_schema")
                if type(model_schema) is dict
                and model_schema.get("type") == "model-fields"
                else None
            )
            extras_keys_schema = (
                model_schema.get("extras_keys_schema")
                if type(model_schema) is dict
                and model_schema.get("type") == "model-fields"
                else None
            )
            extra_predicate = (
                compile_node(extras_schema, nested_config)
                if extras_schema is not None
                else lambda value, seen: True
            )
            extra_key_predicate = (
                compile_node(extras_keys_schema, nested_config)
                if extras_keys_schema is not None
                else lambda value, seen: True
            )
            token = id(node)

            def model(value: Any, seen: set[tuple[int, int]]) -> bool:
                if not _class_is_in_mro(value, model_class):
                    return False
                if _seen_before(value, token, seen):
                    return True
                values = type(_BASE_MODEL_DICT_DESCRIPTOR).__get__(
                    _BASE_MODEL_DICT_DESCRIPTOR, value, type(value)
                )
                if type(values) is not dict or not _has_exact_string_keys(values):
                    return False
                if node.get("root_model"):
                    return dict.__contains__(values, "root") and child(
                        dict.__getitem__(values, "root"), seen
                    )
                if not child(values, seen):
                    return False
                extras = _base_model_extra(value, values)
                if extras is None:
                    return True
                if type(extras) is not dict:
                    return False
                if not _has_exact_string_keys(extras):
                    return False
                if extra_behavior != "allow":
                    return dict.__len__(extras) == 0
                return all(
                    extra_key_predicate(name, seen) and extra_predicate(item, seen)
                    for name, item in dict.items(extras)
                )

            return model
        raise _unsupported_receiver(f"core schema type {kind!r} is not supported")

    return compile_node(schema)


def _compile_receiving_validator(annotation: Any) -> _CompiledReceivingValidator:
    """Compile a non-transforming predicate or reject the receiver at registration."""
    schema = TypeAdapter(annotation).core_schema
    return _CompiledReceivingValidator(_compile_receiving_schema(schema))


def _compile_tool(
    tool: ToolDef,
    identity: int,
    *,
    enforce: bool,
    snapshot_defaults: bool,
) -> _CompiledTool:
    signature, annotations = _resolved_signature(tool.fn)
    if enforce:
        resolved_parameters = {
            parameter.name: parameter.annotation for parameter in tool.parameters
        }
        compiled_parameters: list[inspect.Parameter] = []
        for name, parameter in signature.parameters.items():
            annotation = resolved_parameters.get(name, parameter.annotation)
            if isinstance(annotation, str):
                raise _unsupported_receiver(
                    f"annotation for parameter {name!r} could not be resolved"
                )
            if annotation is None and parameter.annotation is inspect.Parameter.empty:
                annotation = inspect.Parameter.empty
            compiled_parameters.append(parameter.replace(annotation=annotation))
        signature = signature.replace(parameters=compiled_parameters)
        annotations.update(
            {
                name: parameter.annotation
                for name, parameter in signature.parameters.items()
                if parameter.annotation is not inspect.Parameter.empty
            }
        )
    contract = tool.contract
    bindings = (
        tuple(
            _CompiledBinding(
                name,
                source,
                _compile_receiving_validator(signature.parameters[name].annotation)
                if isinstance(source, FromRequest)
                and signature.parameters[name].annotation is not inspect.Parameter.empty
                else None,
            )
            for name, source in contract.bind.items()
        )
        if enforce and contract is not None and contract.bind is not None
        else ()
    )
    bounds = tool.bounds
    output_adapter = (
        TypeAdapter(contract.output) if enforce and contract is not None else None
    )
    return _CompiledTool(
        identity=identity,
        name=tool.name,
        description=tool.description,
        fn=tool.fn,
        signature=signature,
        annotations=MappingProxyType(dict(annotations)),
        required=tool.required,
        minimum=(
            bounds.minimum
            if enforce and bounds is not None
            else (1 if tool.required else 0)
        ),
        maximum=bounds.maximum if enforce and bounds is not None else None,
        bindings=bindings,
        defaults=tuple(
            _CompiledDefault(name, parameter.default)
            for name, parameter in signature.parameters.items()
            if snapshot_defaults
            and parameter.default is not inspect.Parameter.empty
            and (contract is None or contract.bind is None or name not in contract.bind)
        ),
        output_adapter=output_adapter,
        output_validator=(
            _compile_output_validator(output_adapter)
            if output_adapter is not None
            else None
        ),
        enforce_bound_exactly_once=enforce,
    )


def _compile_parameter(param: ParamDef) -> _CompiledParameter:
    """Snapshot one mutable public parameter definition for HTTP construction."""
    return _CompiledParameter(
        name=param.name,
        type_annotation=param.type_annotation,
        description=param.description,
        required=param.required,
        default=param.default,
        annotation=param.annotation,
    )


def _resolved_signature(target: Any) -> tuple[inspect.Signature, dict[str, Any]]:
    """Return a capability signature whose annotations are real type objects."""
    try:
        signature = inspect.signature(target, eval_str=True)
    except (TypeError, NameError):
        signature = inspect.signature(target)
    annotations: dict[str, Any] = {
        name: parameter.annotation
        for name, parameter in signature.parameters.items()
        if parameter.annotation is not inspect.Parameter.empty
    }
    if signature.return_annotation is not inspect.Signature.empty:
        annotations["return"] = signature.return_annotation
    return signature, annotations


def _prepare_request(
    plan: _CompiledEndpoint,
    params: Mapping[str, Any],
) -> _RequestValues:
    """Validate raw external input once, or consume a plan-bound transport snapshot."""
    snapshot = _TRANSPORT_SNAPSHOTS.get(id(params))
    if snapshot is not None and snapshot.reference() is params:
        if isinstance(snapshot, _ConsumedTransport):
            raise ValueError("Validated request transport was already consumed")
        if snapshot.plan is not plan:
            raise ValueError("Validated request belongs to a different endpoint plan")
        # Transfer the already validated graph exactly once. Copying arbitrary
        # application values here is both unnecessary and unsafe: __deepcopy__
        # is application code and can replace or mutate validated values.
        _TRANSPORT_SNAPSHOTS[id(params)] = _ConsumedTransport(snapshot.reference)
        return _RequestValues(snapshot.prompt, typed=snapshot.typed)

    if type(params) is dict or type(params) is _RequestValues:
        # The exact compatibility carrier has no overridable mapping hooks. Its
        # typed view is still untrusted; validate only a built-in copy of the
        # public values, preserving caller isolation and provenance semantics.
        raw_params = dict.copy(params)
    else:
        raise _unsupported_raw_request(
            "outer_mapping_type",
            "raw request input must be an exact dictionary",
        )

    validated = plan.input_validator.validate_python(raw_params)
    fields = _pydantic_fields(validated)
    storage = _BASE_MODEL_DICT_DESCRIPTOR.__get__(validated, type(validated))
    if type(storage) is not dict or not _has_exact_string_keys(storage):
        raise _unsupported_raw_request(
            "canonical_storage_type",
            "validated request has unsupported canonical storage",
        )
    typed = {
        (
            plan.input_field_names[name] if plan.input_field_names is not None else name
        ): dict.__getitem__(storage, name)
        for name in fields
        if dict.__contains__(storage, name)
    }
    prompt = _inert_transport_value(
        validated,
        schema=plan.prompt_schema,
        definitions=plan.prompt_definitions,
    )
    if type(prompt) is not dict:
        raise _unsupported_raw_request(
            "canonical_projection_type",
            "validated request has unsupported canonical projection",
        )
    return _RequestValues(prompt, typed=typed)


def _new_run(plan: _CompiledEndpoint, params: Mapping[str, Any]) -> _EndpointRun:
    request = params.typed if isinstance(params, _RequestValues) else params
    return _EndpointRun(
        request=request,
        states=[_OperationState() for _ in plan.tools],
    )
