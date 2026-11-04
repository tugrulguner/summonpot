"""Declarative deterministic capabilities for agentic endpoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from summonpot.contracts import CallBounds, Operation


@dataclass(frozen=True)
class Dependency:
    """An exact operation exposed to an endpoint agent."""

    operation: Callable[..., Any] | Operation
    required: bool = False
    calls: CallBounds | None = None
    until: str | None = None

    def __post_init__(self) -> None:
        if self.until is not None and (
            type(self.until) is not str
            or not self.until
            or not self.required
            or not isinstance(self.operation, Operation)
        ):
            raise TypeError(
                "Completion requires a required Operation and canonical field name."
            )

    @property
    def bounds(self) -> CallBounds:
        """Resolve the call bounds this dependency actually enforces.

        The marker carries the intent — ``Depends`` is optional, ``Required`` is
        mandatory — and ``calls`` only tightens it. A bare ``Required`` stays "at
        least once" rather than becoming "exactly once", because narrowing it here
        would change what already-written endpoints mean.
        """
        marker_minimum = 1 if self.required else 0
        if self.calls is None:
            return CallBounds(minimum=marker_minimum)
        # `calls` tightens the marker rather than replacing it: AtMost(3) on a
        # Required operation means between 1 and 3, not between 0 and 3, because
        # the marker already said it must run.
        return CallBounds(
            minimum=max(self.calls.minimum, marker_minimum),
            maximum=self.calls.maximum,
        )

    @property
    def callable(self) -> Callable[..., Any]:
        """Return the underlying callable, whether or not a contract wraps it."""
        if isinstance(self.operation, Operation):
            return self.operation.operation
        return self.operation

    @property
    def contract(self) -> Operation | None:
        """Return the operation contract, if this dependency has one."""
        return self.operation if isinstance(self.operation, Operation) else None


def _check_bounds(calls: CallBounds | None, *, required: bool) -> None:
    """Reject call bounds that contradict the marker they are attached to.

    The marker is the primary statement of intent, so a contradiction is a mistake
    in the declaration rather than something to resolve silently in favour of one
    side or the other.
    """
    if calls is None:
        return
    if not required and calls.minimum >= 1:
        raise ValueError(
            f"Depends(...) with calls requiring {calls.describe()} call(s) is "
            "mandatory, not optional. Use Required(...) instead."
        )
    if required and calls.maximum == 0:
        raise ValueError(
            "Required(...) with calls permitting no calls is unsatisfiable. Use "
            "Depends(...) if the operation is optional."
        )


def Depends(
    operation: Callable[..., Any] | Operation,
    *,
    calls: CallBounds | None = None,
) -> Dependency:
    """Expose an operation the agent may call."""
    _check_bounds(calls, required=False)
    return Dependency(operation=operation, calls=calls)


def Required(
    operation: Callable[..., Any] | Operation,
    *,
    calls: CallBounds | None = None,
    until: str | None = None,
) -> Dependency:
    """Expose an operation that must run before successful output."""
    _check_bounds(calls, required=True)
    return Dependency(operation=operation, required=True, calls=calls, until=until)
