"""Private compiled execution contracts for endpoint operations."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import UUID
from weakref import ReferenceType, ref

from pydantic import TypeAdapter
from pydantic_core import SchemaValidator, TzInfo

from summonpot._output_validation import _compile_output_validator
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
    adapter: TypeAdapter[Any] | None


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
    input_adapter: TypeAdapter[Any] | None
    output_model: Any
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


def _inert_transport_value(
    value: Any, ancestors: frozenset[int] = frozenset(), *, native: bool = False
) -> Any:
    """Project known exact types only, without application serialization hooks."""
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
        return {
            key: _inert_transport_value(item, ancestors, native=native)
            for key, item in value.items()
            if type(key) is str
        }
    items = [_inert_transport_value(item, ancestors, native=native) for item in value]
    return kind(items) if native else items


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
    enforce_index = _bound_exact_tool_index(source_tools)
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
    return _CompiledEndpoint(
        path=endpoint.path,
        name=endpoint.name,
        description=endpoint.description,
        return_type=endpoint.return_type,
        parameters=tuple(_compile_parameter(param) for param in endpoint.parameters),
        input_model=endpoint.input_model,
        input_adapter=(
            TypeAdapter(endpoint.input_model)
            if endpoint.input_model is not None
            else None
        ),
        output_model=endpoint.output_model,
        model=endpoint.model,
        method=endpoint.method,
        operation_id=endpoint.operation_id,
        path_parameter_names=tuple(endpoint.path_parameter_names),
        tools=tools,
        direct_tool=direct_index,
    )


def _bound_exact_tool_index(tools: Sequence[ToolDef]) -> int | None:
    """Return the one PR-1 operation eligible for bound enforcement."""
    if len(tools) != 1:
        return None
    tool = tools[0]
    contract = tool.contract
    bounds = tool.bounds
    if (
        not tool.required
        or contract is None
        or contract.bind is None
        or contract.output is None
        or contract.after
        or bounds is None
        or bounds.minimum != 1
        or bounds.maximum != 1
    ):
        return None
    if not all(
        isinstance(source, FromRequest)
        or (isinstance(source, AgentChoice) and source.from_result is None)
        for source in contract.bind.values()
    ):
        return None
    return 0


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


def _class_is_in_mro(value: Any, expected: type[Any]) -> bool:
    """Perform an instance check without a custom metaclass __instancecheck__."""
    value_type = type(value)
    return any(
        base is expected for base in type.__getattribute__(value_type, "__mro__")
    )


def _length_ok(length: int, schema: Mapping[str, Any]) -> bool:
    minimum = schema.get("min_length")
    maximum = schema.get("max_length")
    return (minimum is None or length >= minimum) and (
        maximum is None or length <= maximum
    )


def _number_ok(value: Any, schema: Mapping[str, Any]) -> bool:
    if schema.get("allow_inf_nan") is False:
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


def _compile_receiving_schema(schema: Any) -> _ReceivingPredicate:
    """Compile the hook-free core-schema subset used for receiving checks."""
    definitions: dict[str, Any] = {}
    references: dict[str, _ReceivingPredicate] = {}

    def compile_node(node: Any) -> _ReceivingPredicate:
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
            return compile_node(node["schema"])
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
            holder.append(compile_node(target))
            return deferred
        if kind in {"default", "nullable", "custom-error"}:
            child = compile_node(node["schema"])
            if kind == "nullable":
                return lambda value, seen: value is None or child(value, seen)
            return child
        if kind == "lax-or-strict":
            return compile_node(node["strict_schema"])
        if kind == "json-or-python":
            return compile_node(node["python_schema"])
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
            if kind == "decimal" and node.get("allow_inf_nan") is True:
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
                if kind in {"int", "float", "decimal"} and not _number_ok(value, node):
                    return False
                if kind in {"str", "bytes"} and not _length_ok(len(value), node):
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
                    type(value) is type(expected) and value == expected
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
                compile_node(choice[0] if type(choice) is tuple else choice)
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
            child = compile_node(node.get("items_schema", {"type": "any"}))
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
                compile_node(item) for item in node.get("items_schema", ())
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
            key_predicate = compile_node(node.get("keys_schema", {"type": "any"}))
            value_predicate = compile_node(node.get("values_schema", {"type": "any"}))
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
            return compile_node(node["schema"])
        if kind == "model-fields":
            fields = tuple(
                (name, compile_node(field_schema))
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
            model_class = node["cls"]
            child = compile_node(node["schema"])
            model_schema = node["schema"]
            extra_behavior = node.get("config", {}).get("extra_fields_behavior")
            extras_schema = (
                model_schema.get("extras_schema")
                if type(model_schema) is dict
                and model_schema.get("type") == "model-fields"
                else None
            )
            extra_predicate = (
                compile_node(extras_schema)
                if extras_schema is not None
                else lambda value, seen: True
            )
            token = id(node)

            def model(value: Any, seen: set[tuple[int, int]]) -> bool:
                if not _class_is_in_mro(value, model_class):
                    return False
                if _seen_before(value, token, seen):
                    return True
                values = object.__getattribute__(value, "__dict__")
                if node.get("root_model"):
                    return (
                        type(values) is dict
                        and dict.__contains__(values, "root")
                        and child(dict.__getitem__(values, "root"), seen)
                    )
                if not child(values, seen):
                    return False
                extras = object.__getattribute__(value, "__pydantic_extra__")
                if extras is None:
                    return True
                if type(extras) is not dict:
                    return False
                if extra_behavior != "allow":
                    return dict.__len__(extras) == 0
                return all(
                    type(name) is str and extra_predicate(item, seen)
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
                if signature.parameters[name].annotation is not inspect.Parameter.empty
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
        adapter=(
            TypeAdapter(param.annotation)
            if param.annotation is not None and not isinstance(param.annotation, str)
            else None
        ),
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

    if plan.input_adapter is not None:
        validated = plan.input_adapter.validate_python(deepcopy(dict(params)))
        prompt = validated.model_dump(mode="json", by_alias=True)
        typed = {
            name: getattr(validated, name) for name in type(validated).model_fields
        }
        return _RequestValues(prompt, typed=typed)

    prompt = deepcopy(dict(params))
    typed_source = params
    typed: dict[str, Any] = {}
    for parameter in plan.parameters:
        if parameter.name not in typed_source and parameter.name not in prompt:
            continue
        value = typed_source.get(parameter.name, prompt.get(parameter.name))
        detached = deepcopy(value)
        typed[parameter.name] = (
            parameter.adapter.validate_python(detached)
            if parameter.adapter is not None
            else detached
        )
    return _RequestValues(prompt, typed=typed)


def _new_run(plan: _CompiledEndpoint, params: Mapping[str, Any]) -> _EndpointRun:
    request = params.typed if isinstance(params, _RequestValues) else params
    return _EndpointRun(
        request=request,
        states=[_OperationState() for _ in plan.tools],
    )
