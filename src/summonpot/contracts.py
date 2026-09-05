"""Typed capability contracts.

An endpoint's declaration already says *which* operations may run. These types let it
also say *where each argument's value comes from*, which is what makes the execution
path a computable property rather than a guess.

This module is declaration vocabulary. Registration validates every contract before
serving. The runtime currently enforces the first narrow execution slice: one required
``Exactly(1)`` operation whose arguments come from ``FromRequest``, ``AgentChoice``, or
callable defaults. Result chains, context injection, and broader graph execution remain
later work.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

# ---------------------------------------------------------------------------
# Argument sources
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArgumentSource:
    """Where one operation argument's value comes from."""


@dataclass(frozen=True)
class FromRequest(ArgumentSource):
    """Take the value from a field of the validated request model."""

    field: str


@dataclass(frozen=True)
class FromResult(ArgumentSource):
    """Take the value from a field of an earlier operation's validated output.

    The output is validated against the producing operation's ``output`` type before
    it can be read here, so a later argument can never be bound to an unvalidated
    value.
    """

    operation: Operation
    field: str


@dataclass(frozen=True)
class FromContext(ArgumentSource):
    """Take the value from framework-owned state rather than from the caller."""

    key: str


@dataclass(frozen=True)
class AgentChoice(ArgumentSource):
    """Let the model choose the value.

    The only *argument source* a declaration does not determine. In the shipped
    single-operation bound runtime, ``FromRequest`` and defaulted arguments are hidden
    from the model while ``AgentChoice`` arguments remain in its tool schema. Broader
    result-chain and context bindings remain planned.

    This is a claim about one argument, not about an endpoint. An endpoint whose every
    argument is bound may still need a model — for an unresolved ordering, a choice
    between operations, or a response it cannot compose. Whether an endpoint can run
    without a model is decided by the whole capability graph together with the
    response binding, not by the absence of this source.
    """

    from_result: Operation | None = None
    item_type: Any = None


# ---------------------------------------------------------------------------
# Call bounds
# ---------------------------------------------------------------------------


def _reject_non_count(value: object, field: str) -> None:
    """Require a built-in ``int``, so a bound is always a number of calls.

    ``type(value) is int`` rather than ``isinstance``: ``bool`` is an ``int``
    subclass, so ``Exactly(True)`` otherwise becomes ``Exactly(1)`` -- a
    declaration that means something, from an expression that meant nothing.
    The same exactness rejects an ``IntEnum`` or a NumPy integer, which is the
    intended reading; a call bound is written by hand in a declaration, and a
    caller with one of those can spell ``int(...)``.
    """
    if type(value) is not int:
        # Nothing about the rejected object is rendered -- not the value, and
        # not its type. Both reach us straight from a caller's declaration, so
        # both are caller-controlled: a value may carry a credential, its
        # ``__repr__`` may raise, and a class is free to set ``__name__`` to
        # secret-bearing text or to make even reading it raise from a
        # metaclass. Any of those would either leak into logs or replace this
        # actionable TypeError with an arbitrary exception from somebody
        # else's code. The declaration site in the traceback already says which
        # expression was written, so naming the field and the rule is enough to
        # fix it.
        raise TypeError(
            f"Call bound {field} must be a built-in int. A bound counts "
            "how many times an operation may run."
        )


@dataclass(frozen=True)
class CallBounds:
    """How many times an operation may run within one request."""

    minimum: int = 0
    maximum: int | None = None

    def __post_init__(self) -> None:
        # Kind before value. A bound counts operation starts, so a float, a
        # string or a bool is the wrong *kind* of thing rather than a bad count,
        # and conflating the two produced three different outcomes for three
        # equally invalid declarations: `Exactly(1.5)` was accepted, `Exactly(
        # True)` was accepted as 1, and `AtLeast("1")` died in the `<` below
        # with a comparison TypeError that named neither the field nor the rule.
        _reject_non_count(self.minimum, "minimum")
        if self.maximum is not None:
            _reject_non_count(self.maximum, "maximum")

        if self.minimum < 0:
            raise ValueError("Call bounds cannot require a negative number of calls.")
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError(
                f"Call bounds are unsatisfiable: maximum {self.maximum} is below "
                f"minimum {self.minimum}."
            )

    def describe(self) -> str:
        """Render the bounds for an error message."""
        if self.maximum is None:
            return f"at least {self.minimum}"
        if self.minimum == self.maximum:
            return f"exactly {self.minimum}"
        return f"between {self.minimum} and {self.maximum}"


def Exactly(count: int) -> CallBounds:
    """Run this operation exactly ``count`` times."""
    return CallBounds(minimum=count, maximum=count)


def AtLeast(count: int) -> CallBounds:
    """Run this operation at least ``count`` times."""
    return CallBounds(minimum=count)


def AtMost(count: int) -> CallBounds:
    """Run this operation at most ``count`` times."""
    return CallBounds(maximum=count)


def Between(minimum: int, maximum: int) -> CallBounds:
    """Run this operation between ``minimum`` and ``maximum`` times."""
    return CallBounds(minimum=minimum, maximum=maximum)


# ---------------------------------------------------------------------------
# Operation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Operation:
    """A capability together with the contract governing how it may be called.

    Operations are graph vertices — ``FromResult`` and ``after`` both reference them —
    so they compare and hash **by identity**. Two separately declared operations are
    two declarations even when they look alike, which is what makes ``FromResult(op,
    ...)`` point at one specific node rather than at whichever declaration happens to
    match structurally. Identity also keeps the semantics the same whether or not
    ``bind`` is present; value equality would have to hash the bindings, which means
    imposing an order on a mapping that has none.

    Declared away from the endpoint so the endpoint signature stays a declaration
    rather than a configuration object::

        lookup_by_customer_id = Operation(
            lookup_customer,
            bind={"customer_id": FromRequest("customer_id")},
            output=Customer,
        )

        @summon("/orders")
        def place_order(
            request: OrderRequest,
            customer=Required(lookup_by_customer_id),
        ) -> OrderResponse:
            \"\"\"Place an order for this customer.\"\"\"
            ...
    """

    operation: Callable[..., Any]
    bind: Mapping[str, ArgumentSource] | None = None
    output: Any = None
    after: Sequence[Operation] = ()

    def __post_init__(self) -> None:
        # The bindings decide which arguments the model may choose, so they are the
        # security boundary. `frozen=True` only stops the attribute being reassigned,
        # so without a snapshot the mapping stays writable through this attribute and
        # through whatever dict the caller passed in - after registration, and after
        # any validation the declaration has already passed.
        if self.bind is not None:
            object.__setattr__(self, "bind", MappingProxyType(dict(self.bind)))
        # `after` is ordering, which the capability graph reads exactly as it reads
        # the bindings. Annotated as a tuple but not normalised, a caller-owned list
        # stayed writable after the contract was registered and validated.
        object.__setattr__(self, "after", tuple(self.after))

    def with_bind(self, **bindings: ArgumentSource) -> Operation:
        """Return a copy of this operation with some bindings replaced.

        For the case where two endpoints need the same callable reading differently
        named request fields. The endpoint still receives a complete ``Operation``;
        this only avoids restating the parts that do not change.
        """
        merged = {**(self.bind or {}), **bindings}
        return replace(self, bind=merged)


__all__ = [
    "AgentChoice",
    "ArgumentSource",
    "AtLeast",
    "AtMost",
    "Between",
    "CallBounds",
    "Exactly",
    "FromContext",
    "FromRequest",
    "FromResult",
    "Operation",
]
