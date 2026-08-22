"""Registration-time validation of typed capability contracts.

Every check here runs when the endpoint is declared, so a contract that cannot be
satisfied fails at import rather than part-way through a request. Nothing here
executes an operation or inspects a request.

There is deliberately no cycle detection. `Operation` is frozen and snapshots both
`bind` and `after`, and an edge can only name a node that already exists, so a cycle
cannot be built through the public API — only by bypassing immutability with
`object.__setattr__`. If a later representation can express one, detection belongs
with the graph that can.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from types import UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel

from summonpot.contracts import AgentChoice, FromRequest, FromResult, Operation

_VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


# ---------------------------------------------------------------------------
# Conservative type comparison
#
# Only the relations binding validation needs, deliberately narrow. Every
# function answers "is this provably wrong?" - anything it cannot decide is
# accepted, because a guard that refuses a valid declaration is worse than one
# that misses an invalid one.
# ---------------------------------------------------------------------------

_SELECTABLE = (list, set, frozenset, Sequence)
# Iterable, but not a collection of selectable values: a string yields characters
# and a mapping yields keys.
_NOT_SELECTABLE = (str, bytes, bytearray, dict, Mapping)


def _unwrap(annotation: Any) -> Any:
    """Strip `Annotated` down to the type it decorates."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _is_unknown(annotation: Any) -> bool:
    """Report whether nothing can be proven about this annotation."""
    if annotation is None or annotation is Any or annotation is object:
        return True
    return isinstance(annotation, str | TypeVar)


def _safe_issubclass(source: Any, target: Any) -> bool | None:
    """Return the subclass relation, or None when it cannot be established.

    `issubclass` raises for a Protocol that is not `runtime_checkable`, among
    others. An unanswerable question is unknown, never a registration failure.
    """
    if not (isinstance(source, type) and isinstance(target, type)):
        return None
    try:
        return issubclass(source, target)
    except TypeError:
        return None


def _union_members(annotation: Any) -> tuple[Any, ...] | None:
    """Return a union's members, or None if this is not a union."""
    if get_origin(annotation) in (Union, UnionType):
        return get_args(annotation)
    return None


def _widens_numerically(source: Any, target: Any) -> bool:
    """Report whether the numeric tower permits this widening.

    Based on the subclass relation rather than identity, so `bool` widens like the
    `int` it is.
    """
    if _safe_issubclass(source, int) and target in (float, complex):
        return True
    return bool(_safe_issubclass(source, float) and target is complex)


def _is_compatible(source: Any, target: Any) -> bool:
    """Report whether a value of type `source` may satisfy `target`.

    True also means "cannot be disproven".
    """
    source, target = _unwrap(source), _unwrap(target)

    if _is_unknown(source) or _is_unknown(target) or source is target:
        return True

    # Any member of a union source may arrive, so all of them must fit; a union
    # target is satisfied by fitting any one member.
    members = _union_members(source)
    if members is not None:
        return all(_is_compatible(member, target) for member in members)
    members = _union_members(target)
    if members is not None:
        return any(_is_compatible(source, member) for member in members)

    source_values = get_args(source) if get_origin(source) is Literal else None
    target_values = get_args(target) if get_origin(target) is Literal else None
    if source_values is not None and target_values is not None:
        # Both value sets are finite and known, so disjointness is provable.
        return all(value in target_values for value in source_values)
    if source_values is not None:
        return all(_is_compatible(type(value), target) for value in source_values)
    if target_values is not None:
        # The value cannot be proven, but the type of every permitted value can.
        return any(_is_compatible(source, type(value)) for value in target_values)

    if get_origin(source) is not None or get_origin(target) is not None:
        return _generics_compatible(source, target)

    if _widens_numerically(source, target):
        return True
    related = _safe_issubclass(source, target)
    return True if related is None else related


def _generics_compatible(source: Any, target: Any) -> bool:
    """Compare two annotations where at least one is parameterised."""
    source_origin, target_origin = get_origin(source), get_origin(target)
    if source_origin is None or target_origin is None:
        return True

    if source_origin is not target_origin:
        related = _safe_issubclass(source_origin, target_origin)
        if related is None:
            return True
        if not related:
            return False
        # The origins are related, but that says nothing about the parameters -
        # list[int] is not a Sequence[str]. Fall through and compare them.

    raw_source, raw_target = get_args(source), get_args(target)
    source_args = [a for a in raw_source if a is not Ellipsis]
    target_args = [a for a in raw_target if a is not Ellipsis]

    source_is_fixed = get_origin(source) is tuple and not _is_homogeneous_tuple(
        raw_source
    )
    target_is_fixed = get_origin(target) is tuple and not _is_homogeneous_tuple(
        raw_target
    )

    # A fixed tuple is a sequence of its declared members, so a target admitting any
    # number of one element type - tuple[T, ...] or Sequence[T] - is satisfied only
    # if every member fits T. The differing count is not what makes it unknown.
    if source_is_fixed and not target_is_fixed and len(target_args) == 1:
        return all(_is_compatible(member, target_args[0]) for member in source_args)

    # Two fixed tuples describe positions, so different lengths cannot match.
    if (
        source_is_fixed
        and target_is_fixed
        and raw_source
        and raw_target
        and len(source_args) != len(target_args)
    ):
        return False

    if not source_args or not target_args or len(source_args) != len(target_args):
        return True
    return all(
        _is_compatible(s, t) for s, t in zip(source_args, target_args, strict=True)
    )


def _is_homogeneous_tuple(args: tuple[Any, ...]) -> bool:
    """Report whether these arguments spell `tuple[T, ...]`."""
    return len(args) == 2 and args[1] is Ellipsis


def _selectable_item_type(output: Any) -> tuple[bool, Any]:
    """Describe what a model could select from a result of type `output`."""
    output = _unwrap(output)
    if _is_unknown(output):
        return True, None

    # Any member of a union may arrive, so the result is selectable only if every
    # member is. Element types are combined only when they agree; disagreement is
    # left unknown rather than modelled.
    members = _union_members(output)
    if members is not None:
        element_types = set()
        for member in members:
            if _is_unknown(member):
                return True, None
            selectable, element = _selectable_item_type(member)
            if not selectable:
                return False, None
            element_types.add(element)
        return True, element_types.pop() if len(element_types) == 1 else None

    origin = get_origin(output) or output
    args = get_args(output)

    if origin is tuple:
        # Only the homogeneous form is a collection of like items. A fixed tuple has
        # a different type at each position, so "select an item" has no single item
        # type to constrain. Bare `tuple` is unparameterised and therefore unknown,
        # which is not the same as `tuple[()]` - that one provably has no items.
        if get_origin(output) is None:
            return True, None
        if _is_homogeneous_tuple(args):
            return True, args[0]
        return False, None

    # Checked one type at a time: _safe_issubclass answers "unknown" for a union
    # target, which would let these fall through to the Sequence test below - and a
    # str *is* a Sequence, of characters.
    if any(_safe_issubclass(origin, excluded) for excluded in _NOT_SELECTABLE):
        return False, None
    if any(_safe_issubclass(origin, candidate) for candidate in _SELECTABLE):
        return True, args[0] if args else None
    return False, None


def _describe(annotation: Any) -> str:
    """Render an annotation for an error message."""
    annotation = _unwrap(annotation)
    if annotation is None:
        return "unannotated"
    return getattr(annotation, "__name__", None) or str(annotation)


def _bindable_request_fields(
    input_model: type[BaseModel] | None, parameters: list[Any]
) -> set[str]:
    """Return the names `FromRequest` may refer to for this endpoint."""
    if input_model is not None:
        return set(input_model.model_fields)
    return {parameter.name for parameter in parameters}


def _request_annotations(
    input_model: type[BaseModel] | None, parameters: list[Any]
) -> dict[str, Any]:
    """Return the endpoint's request field types, keyed by the name bindings use."""
    if input_model is not None:
        return {
            name: field.annotation for name, field in input_model.model_fields.items()
        }
    return {parameter.name: parameter.annotation for parameter in parameters}


def _readable_fields(output: Any) -> set[str] | None:
    """Return the fields a result exposes, or None if it exposes none statically."""
    if isinstance(output, type) and issubclass(output, BaseModel):
        return set(output.model_fields)
    return None


def _argument_annotations(tool: Any) -> dict[str, Any]:
    """Return an operation's resolved argument types, keyed by name.

    Read from the normalized ParamDef list rather than by re-inspecting the callable,
    so this agrees with the arguments the model is actually offered for a bound
    method, a callable object or a partial.
    """
    return {p.name: p.annotation for p in tool.parameters}


def validate_contracts(
    *,
    endpoint: str,
    tools: list[Any],
    input_model: type[BaseModel] | None,
    parameters: list[Any],
) -> None:
    """Check every declared contract on one endpoint.

    Raises `TypeError` naming the endpoint, the operation, and the parameter, so the
    message says what to change rather than only what is wrong.
    """
    declared = {tool.contract for tool in tools if tool.contract is not None}
    request_fields = _bindable_request_fields(input_model, parameters)

    for tool in tools:
        contract = tool.contract
        if contract is None:
            continue
        # `after` states an ordering against another operation, so that operation has
        # to be one this endpoint declares. Checked even without bindings, because
        # ordering is part of the capability graph in its own right.
        for predecessor in contract.after:
            _require_declared(
                endpoint=endpoint,
                operation=tool.name,
                referenced=predecessor,
                declared=declared,
                what="orders itself after",
            )
        if contract.bind is None:
            # A contract that declares no bindings keeps the existing behaviour:
            # every argument is chosen by the model.
            continue
        _validate_bindings(
            endpoint=endpoint,
            operation=tool.name,
            contract=contract,
            declared=declared,
            request_fields=request_fields,
            argument_types=_argument_annotations(tool),
            request_types=_request_annotations(input_model, parameters),
        )


def _require_declared(
    *,
    endpoint: str,
    operation: str,
    referenced: Operation,
    declared: set[Operation],
    what: str,
) -> None:
    """Reject a reference to an operation outside the endpoint's capability set.

    The endpoint's declared operations are its whole capability set. A reference to
    anything else would put an operation into the graph that the endpoint never
    exposed.
    """
    if referenced not in declared:
        name = getattr(
            referenced.operation, "__name__", type(referenced.operation).__name__
        )
        raise TypeError(
            f"Endpoint {endpoint!r}: operation {operation!r} {what} {name!r}, which "
            "the endpoint does not declare. Add it with Depends(...) or "
            "Required(...), or reference one that is declared."
        )


def _validate_bindings(
    *,
    endpoint: str,
    operation: str,
    contract: Operation,
    declared: set[Operation],
    request_fields: set[str],
    argument_types: dict[str, Any],
    request_types: dict[str, Any],
) -> None:
    """Check one operation's bindings against the endpoint that declares it."""
    bind = contract.bind or {}
    signature = inspect.signature(contract.operation)

    # A contracted operation may not take *args or **kwargs. Their schema is
    # open-ended - pydantic-ai emits `additionalProperties: true` - so the model could
    # pass keys the contract never named, which is the authority a typed capability
    # exists to close. A bare callable is unaffected; wrap the operation in one with
    # explicit parameters to give it a contract.
    variadic = [
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind in _VARIADIC
    ]
    if variadic:
        raise TypeError(
            f"Endpoint {endpoint!r}: operation {operation!r} declares bind but takes "
            f"{', '.join('*' + n if signature.parameters[n].kind is inspect.Parameter.VAR_POSITIONAL else '**' + n for n in variadic)}. "
            "A contracted operation needs explicit parameters, because a variadic "
            "signature lets the model pass arguments the contract never named. Wrap "
            "it in a function with named parameters."
        )

    argument_names = list(signature.parameters)
    defaulted = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }

    # A binding for an argument the operation does not take is a typo that would
    # otherwise surface as a TypeError mid-request.
    for name in bind:
        if name not in argument_names:
            raise TypeError(
                f"Endpoint {endpoint!r} binds {name!r} for operation {operation!r}, "
                f"which takes no such argument. It takes: "
                f"{', '.join(argument_names) or 'no arguments'}."
            )

    # Declaring `bind` opts into the contract, so it has to cover every argument the
    # caller must supply. An argument the model may choose is written AgentChoice()
    # rather than left out, so a model-controlled argument is never the result of an
    # omission. An argument with a default is already determined - it takes that
    # default, and is not offered to the model - so leaving it out is a choice.
    for name in argument_names:
        if name not in bind and name not in defaulted:
            raise TypeError(
                f"Endpoint {endpoint!r} leaves argument {name!r} of operation "
                f"{operation!r} unbound, and it has no default. Every argument of an "
                "operation that declares bind must have a source; use AgentChoice() "
                "to let the model choose it."
            )

    for name, source in bind.items():
        if isinstance(source, FromRequest):
            _validate_from_request(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                source=source,
                request_fields=request_fields,
            )
            _require_compatible(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                wanted=argument_types.get(name),
                supplied=request_types.get(source.field),
                origin=f"request field {source.field!r}",
            )
        elif isinstance(source, FromResult):
            _require_declared(
                endpoint=endpoint,
                operation=operation,
                referenced=source.operation,
                declared=declared,
                what=f"binds {name!r} from",
            )
            _validate_result_field(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                source=source,
            )
            _require_compatible(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                wanted=argument_types.get(name),
                supplied=_result_field_type(source),
                origin=(
                    f"field {source.field!r} of {_operation_name(source.operation)!r}"
                ),
            )
        elif isinstance(source, AgentChoice) and source.from_result is not None:
            _require_declared(
                endpoint=endpoint,
                operation=operation,
                referenced=source.from_result,
                declared=declared,
                what=f"offers {name!r} from",
            )
            # Offering a result to the model puts it into agent context, so it has
            # the same prerequisite as reading a field from it: the producer must
            # declare an output type, or the value reaches the model unvalidated.
            # No field check here - AgentChoice names no field.
            _require_validatable_output(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                producer=source.from_result,
            )
            _require_selectable(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                source=source,
            )
        if isinstance(source, AgentChoice):
            # Whatever the model picks still has to fit the argument receiving it.
            # Checked for every choice, including one with no producer behind it.
            _require_compatible(
                endpoint=endpoint,
                operation=operation,
                argument=name,
                wanted=argument_types.get(name),
                supplied=_chosen_type(source),
                origin="the model's choice",
            )


def _operation_name(contract: Operation) -> str:
    """Render an operation for an error message."""
    return getattr(contract.operation, "__name__", type(contract.operation).__name__)


def _result_field_type(source: FromResult) -> Any:
    """Return the declared type of the output field a binding reads."""
    output = source.operation.output
    if isinstance(output, type) and issubclass(output, BaseModel):
        field = output.model_fields.get(source.field)
        if field is not None:
            return field.annotation
    return None


def _require_compatible(
    *,
    endpoint: str,
    operation: str,
    argument: str,
    wanted: Any,
    supplied: Any,
    origin: str,
) -> None:
    """Reject a binding whose value provably cannot satisfy the argument.

    Only a definite mismatch is rejected. An unresolved annotation, `Any`, or a shape
    the comparison does not model is accepted, because refusing what cannot be proven
    would block valid declarations.
    """
    if _is_compatible(supplied, wanted):
        return
    raise TypeError(
        f"Endpoint {endpoint!r} binds {origin} ({_describe(supplied)}) to argument "
        f"{argument!r} of operation {operation!r} ({_describe(wanted)}). Those types "
        "are incompatible."
    )


def _chosen_type(source: AgentChoice) -> Any:
    """Return the declared type of a value the model chooses, if it is known.

    A producer's element type wins over `item_type`, because the model can only pick
    values the producer actually returned. Declaring `item_type=Any` narrows nothing
    and must not erase what the producer already proved.
    """
    if source.from_result is not None:
        element = _selectable_item_type(source.from_result.output)[1]
        if not _is_unknown(element):
            return element
    return source.item_type


def _require_selectable(
    *, endpoint: str, operation: str, argument: str, source: AgentChoice
) -> None:
    """Reject offering the model a choice from a result it cannot choose from."""
    producer = source.from_result
    if producer is None:  # pragma: no cover - guarded by the caller
        return

    selectable, item_type = _selectable_item_type(producer.output)
    if not selectable:
        raise TypeError(
            f"Endpoint {endpoint!r} offers argument {argument!r} of operation "
            f"{operation!r} as a choice from the result of "
            f"{_operation_name(producer)!r}, typed "
            f"{_describe(producer.output)}. A choice is made from a list, set, tuple "
            "or sequence; that type is not a collection of selectable items."
        )

    if source.item_type is not None and not _is_compatible(item_type, source.item_type):
        raise TypeError(
            f"Endpoint {endpoint!r} offers argument {argument!r} of operation "
            f"{operation!r} as a choice of {_describe(source.item_type)}, but "
            f"{_operation_name(producer)!r} returns a collection of "
            f"{_describe(item_type)}."
        )


def _validate_from_request(
    *,
    endpoint: str,
    operation: str,
    argument: str,
    source: FromRequest,
    request_fields: set[str],
) -> None:
    """Check that a request binding names a field the endpoint declares."""
    if not request_fields:
        raise TypeError(
            f"Endpoint {endpoint!r} binds {argument!r} of operation {operation!r} to "
            f"request field {source.field!r}, but the endpoint declares no request "
            "fields."
        )
    if source.field not in request_fields:
        raise TypeError(
            f"Endpoint {endpoint!r} binds {argument!r} of operation {operation!r} to "
            f"request field {source.field!r}, which the request does not declare. "
            f"Available: {', '.join(sorted(request_fields))}."
        )


def _require_validatable_output(
    *, endpoint: str, operation: str, argument: str, producer: Operation
) -> None:
    """Reject consuming a result the producer never gave a type to.

    A result reaches agent context whether it is read from or offered as a choice,
    and the invariant is the same either way: it must be validated against a declared
    type before it gets there.
    """
    if producer.output is None:
        name = getattr(
            producer.operation, "__name__", type(producer.operation).__name__
        )
        raise TypeError(
            f"Endpoint {endpoint!r} consumes the result of {name!r} for argument "
            f"{argument!r} of operation {operation!r}, but {name!r} declares no "
            "output type. Give it output=... so the result can be validated before "
            "it is used."
        )


def _validate_result_field(
    *, endpoint: str, operation: str, argument: str, source: FromResult
) -> None:
    """Check that a result binding reads a field the producer's output declares."""
    producer = source.operation
    _require_validatable_output(
        endpoint=endpoint, operation=operation, argument=argument, producer=producer
    )

    fields = _readable_fields(producer.output)
    if fields is None:
        name = getattr(producer.output, "__name__", repr(producer.output))
        raise TypeError(
            f"Endpoint {endpoint!r} binds {argument!r} of operation {operation!r} to "
            f"field {source.field!r} of a result typed {name}, whose fields cannot be "
            "checked. Declare output= as a Pydantic model to read a field from it."
        )
    if source.field not in fields:
        raise TypeError(
            f"Endpoint {endpoint!r} binds {argument!r} of operation {operation!r} to "
            f"field {source.field!r}, which {producer.output.__name__} does not "
            f"declare. Available: {', '.join(sorted(fields))}."
        )
