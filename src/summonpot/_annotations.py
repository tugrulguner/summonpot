"""Shared annotation inspection for endpoints and capabilities.

Endpoint registration and capability construction ask the same three questions of a
signature, so the answers live here once rather than in two copies that can drift.
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable
from typing import Any


def type_name(tp: Any) -> str:
    """Render an annotation as a short display string."""
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        return " | ".join(type_name(a) for a in typing.get_args(tp))

    if hasattr(tp, "__origin__"):
        origin = tp.__origin__
        args = tp.__args__
        if origin is list and args:
            return f"list[{type_name(args[0])}]"
        if origin is dict and len(args) >= 2:
            return f"dict[{type_name(args[0])}, {type_name(args[1])}]"
        if origin is tuple:
            return f"tuple[{', '.join(type_name(a) for a in args)}]"
        return type_name(origin)
    if tp is type(None):
        return "None"
    if hasattr(tp, "__name__"):
        return tp.__name__
    return str(tp)


def get_type_str(
    pname: str,
    param: inspect.Parameter,
    hints: dict[str, Any],
) -> str:
    """Render one parameter's annotation, preferring resolved hints."""
    if pname in hints:
        return type_name(hints[pname])
    if param.annotation is not inspect.Parameter.empty:
        return type_name(param.annotation)
    return "str"


def _resolve_annotation(annotation: Any, globalns: dict[str, Any]) -> Any:
    """Resolve an annotation, including forward references nested inside it.

    Under ``from __future__ import annotations`` an annotation is stored as source
    text, and a quoted reference may sit *inside* an otherwise resolvable type:
    ``list["Request"]`` evaluates to ``list['Request']``, whose argument is still a
    string. ``typing.get_type_hints`` applies the same recursive treatment the type
    system uses, so containers, unions and optionals all resolve.

    Returns the resolved object, or the name that failed to resolve so the caller can
    report it.
    """

    def holder() -> None: ...

    holder.__annotations__ = {"value": annotation}
    try:
        # include_extras keeps Annotated metadata, which carries the parameter's
        # validation constraints; dropping it would silently weaken the contract.
        return typing.get_type_hints(holder, globalns, include_extras=True)["value"]
    except NameError as exc:
        # `NameError.name` is the single name that could not be resolved, which reads
        # far better than the whole annotation source.
        return exc.name or annotation
    except Exception:
        return annotation


def safe_get_type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """Resolve a callable's annotations.

    Each annotation is resolved independently: one unresolvable name would otherwise
    fail the whole call and make every healthy annotation beside it look broken too,
    so the error would name the wrong parameter.
    """
    globalns = getattr(func, "__globals__", {})
    return {
        name: _resolve_annotation(annotation, globalns)
        for name, annotation in inspect.get_annotations(func, eval_str=False).items()
    }


def reject_unresolved(annotation: Any, *, where: str, endpoint: str) -> None:
    """Fail loudly when an annotation could not be resolved to a type.

    An unresolved annotation is still a string, so nothing downstream can tell a
    Pydantic model from a plain value. Degrading to an untyped endpoint would discard
    exactly the contract the framework exists to enforce.
    """
    if isinstance(annotation, str):
        raise TypeError(
            f"Could not resolve the annotation {annotation!r} for {where} of "
            f"endpoint {endpoint!r}. summonpot builds the request and response "
            "contracts from these annotations and will not fall back to an untyped "
            "endpoint. Import the type at runtime rather than only under "
            "TYPE_CHECKING, and declare it at module scope."
        )
