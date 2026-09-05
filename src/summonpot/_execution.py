"""Private compiled execution contracts for endpoint operations."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from weakref import ReferenceType, ref

from pydantic import TypeAdapter
from pydantic_core import SchemaValidator

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
    path_parameter_names: tuple[str, ...]
    tools: tuple[_CompiledTool, ...]
    direct_tool: int | None


_REGISTERED_PLANS: dict[int, tuple[ReferenceType[EndpointDef], _CompiledEndpoint]] = {}


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


def _compile_tool(
    tool: ToolDef,
    identity: int,
    *,
    enforce: bool,
    snapshot_defaults: bool,
) -> _CompiledTool:
    signature, annotations = _resolved_signature(tool.fn)
    contract = tool.contract
    bindings = (
        tuple(_CompiledBinding(name, source) for name, source in contract.bind.items())
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
    """Validate and snapshot raw input or copy an adapter-validated request view."""
    if plan.input_adapter is not None:
        validated = plan.input_adapter.validate_python(deepcopy(dict(params)))
        prompt = validated.model_dump(mode="json", by_alias=True)
        typed = {
            name: getattr(validated, name) for name in type(validated).model_fields
        }
        return _RequestValues(prompt, typed=typed)

    prompt = deepcopy(dict(params))
    typed_source = params.typed if isinstance(params, _RequestValues) else params
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
