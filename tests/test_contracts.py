"""Tests for typed capability contracts.

Step 01 of the typed-contract work: this is vocabulary, so the tests pin the shape of
the declaration and the rules that reject a contradictory one. Nothing consumes the
bindings yet.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import BaseModel

from summonpot import (
    AgentChoice,
    AtLeast,
    AtMost,
    Between,
    CallBounds,
    Depends,
    Exactly,
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)


class Customer(BaseModel):
    customer_id: str
    tier: str


class OrderRequest(BaseModel):
    customer_id: str
    sku: str


class OrderResponse(BaseModel):
    order_id: str


def lookup_customer(customer_id: str) -> Customer:
    """Look up a customer."""
    return Customer(customer_id=customer_id, tier="standard")


def place_order(customer_id: str, sku: str) -> OrderResponse:
    """Place an order."""
    return OrderResponse(order_id="o1")


# --- the declaration ---------------------------------------------------------


def test_operation_carries_bindings_and_output():
    contract = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )

    assert contract.operation is lookup_customer
    assert contract.bind == {"customer_id": FromRequest("customer_id")}
    assert contract.output is Customer


def test_argument_sources_compare_by_value():
    """Two identical bindings are the same binding; the graph relies on this."""
    assert FromRequest("customer_id") == FromRequest("customer_id")
    assert FromRequest("customer_id") != FromRequest("account_id")
    assert FromContext("request_id") == FromContext("request_id")


def test_from_result_names_the_producing_operation():
    lookup = Operation(lookup_customer, output=Customer)
    source = FromResult(lookup, "tier")

    assert source.operation is lookup
    assert source.field == "tier"


def test_agent_choice_is_the_only_undetermined_source():
    """Every other source resolves to one value; this is what makes a path provable."""
    determined = [
        FromRequest("x"),
        FromResult(Operation(lookup_customer), "y"),
        FromContext("z"),
    ]

    assert all(not isinstance(s, AgentChoice) for s in determined)
    assert isinstance(AgentChoice(), AgentChoice)


# --- reuse -------------------------------------------------------------------


def test_with_bind_returns_a_separate_operation():
    """Reuse creates a second contract rather than an endpoint-local override."""
    by_customer = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )
    by_account = by_customer.with_bind(customer_id=FromRequest("account_id"))

    assert by_account is not by_customer
    assert by_customer.bind == {"customer_id": FromRequest("customer_id")}
    assert by_account.bind == {"customer_id": FromRequest("account_id")}
    # The underlying callable and the rest of the contract are shared.
    assert by_account.operation is lookup_customer
    assert by_account.output is Customer


# --- call bounds -------------------------------------------------------------


@pytest.mark.parametrize(
    ("bounds", "minimum", "maximum"),
    [
        (Exactly(1), 1, 1),
        (AtLeast(2), 2, None),
        (AtMost(3), 0, 3),
    ],
)
def test_call_bound_helpers(bounds, minimum, maximum):
    assert (bounds.minimum, bounds.maximum) == (minimum, maximum)


def test_unsatisfiable_bounds_are_rejected():
    with pytest.raises(ValueError, match="unsatisfiable"):
        CallBounds(minimum=2, maximum=1)


# A bound counts operation starts. These are the kinds of value that cannot be
# one, including `bool` -- which is an `int` subclass, so it used to be accepted
# silently as 0 or 1.
NOT_A_COUNT = [
    pytest.param(True, id="bool-true"),
    pytest.param(False, id="bool-false"),
    pytest.param(1.5, id="float"),
    pytest.param(2.0, id="whole-float"),
    pytest.param("1", id="str"),
    pytest.param(Decimal(1), id="decimal"),
    pytest.param(Fraction(1, 1), id="fraction"),
    pytest.param([1], id="list"),
]

# `None` is deliberately absent above: it is `CallBounds.maximum`'s documented
# "unbounded" sentinel, so rejecting it would break the existing default rather
# than catch a wrong kind of value. It is still not a valid *minimum*.


@pytest.mark.parametrize("value", NOT_A_COUNT)
@pytest.mark.parametrize("helper", [Exactly, AtLeast, AtMost])
def test_a_single_argument_helper_rejects_a_non_count(helper, value):
    with pytest.raises(TypeError, match="must be a built-in int"):
        helper(value)


@pytest.mark.parametrize("helper", [Exactly, AtLeast])
def test_a_minimum_setting_helper_rejects_none(helper):
    with pytest.raises(TypeError, match="minimum must be a built-in int"):
        helper(None)


def test_an_absent_maximum_still_means_unbounded():
    """The sentinel predates this check and keeps working."""
    assert CallBounds(minimum=1).maximum is None
    assert AtLeast(1).maximum is None


@pytest.mark.parametrize("value", NOT_A_COUNT)
def test_between_rejects_a_non_count_minimum(value):
    with pytest.raises(TypeError, match="minimum must be a built-in int"):
        Between(value, 3)


@pytest.mark.parametrize("value", NOT_A_COUNT)
def test_between_rejects_a_non_count_maximum(value):
    with pytest.raises(TypeError, match="maximum must be a built-in int"):
        Between(1, value)


@pytest.mark.parametrize("field", ["minimum", "maximum"])
def test_the_error_names_the_offending_bound(field):
    """A message that does not say which end is wrong sends you reading source."""
    with pytest.raises(TypeError) as excinfo:
        CallBounds(**{field: 1.5, **({"minimum": 1} if field == "maximum" else {})})

    message = str(excinfo.value)
    assert field in message
    assert "built-in int" in message


def test_the_error_does_not_echo_the_rejected_value():
    """A declaration may hold a credential, so no part of it is rendered."""
    secret = "sk-live-2f8c41d9e7b0"

    with pytest.raises(TypeError) as excinfo:
        Exactly(secret)  # pyright: ignore[reportArgumentType]

    message = str(excinfo.value)
    assert secret not in message
    assert message == (
        "Call bound minimum must be a built-in int. A bound counts "
        "how many times an operation may run."
    )


def test_a_value_whose_repr_raises_still_gets_the_actionable_error():
    """Rendering the value would hand control to the caller's ``__repr__``."""

    class Unprintable:
        def __repr__(self) -> str:
            raise RuntimeError("repr exploded")

    with pytest.raises(TypeError, match="must be a built-in int"):
        Exactly(Unprintable())  # pyright: ignore[reportArgumentType]


def test_a_hostile_type_name_never_reaches_the_error():
    """``__name__`` is caller-controlled too, so it is not a safe substitute."""

    class Secretive:
        pass

    Secretive.__name__ = "sk-live-2f8c41d9e7b0"

    with pytest.raises(TypeError) as excinfo:
        Exactly(Secretive())  # pyright: ignore[reportArgumentType]

    assert "sk-live-2f8c41d9e7b0" not in str(excinfo.value)


def test_a_type_whose_name_raises_still_gets_the_actionable_error():
    """A metaclass can make even reading ``__name__`` hand over control."""

    class Hostile(type):
        @property
        def __name__(cls) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
            raise RuntimeError("name exploded")

    class Unnameable(metaclass=Hostile):
        pass

    with pytest.raises(TypeError, match="must be a built-in int"):
        Exactly(Unnameable())  # pyright: ignore[reportArgumentType]


def test_a_negative_bound_is_reported_without_a_repr_hazard():
    """A built-in int is safe to name, and the count is the useful detail."""
    with pytest.raises(ValueError, match="negative"):
        AtLeast(-1)


def test_a_bool_is_not_silently_a_count():
    """`Exactly(True)` is an expression that meant nothing becoming one that does."""
    with pytest.raises(TypeError, match="must be a built-in int"):
        Exactly(True)  # pyright: ignore[reportArgumentType]

    # The comparison it used to reach would have made this Exactly(1).
    assert CallBounds(minimum=1, maximum=1) == Exactly(1)


def test_a_negative_count_is_still_a_value_error_not_a_type_error():
    """Right kind of value, invalid value -- the distinction is deliberate."""
    with pytest.raises(ValueError, match="negative"):
        AtLeast(-1)

    with pytest.raises(ValueError, match="unsatisfiable"):
        Between(2, 1)


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        (Exactly(0), (0, 0)),
        (AtMost(0), (0, 0)),
        (AtLeast(0), (0, None)),
        (Between(0, 0), (0, 0)),
    ],
)
def test_zero_bounds_remain_constructible(bounds, expected):
    """Zero is a valid count; only the *kind* check is new."""
    assert (bounds.minimum, bounds.maximum) == expected


@pytest.mark.parametrize(
    ("bounds", "description"),
    [
        (Exactly(2), "exactly 2"),
        (AtLeast(2), "at least 2"),
        (AtMost(2), "between 0 and 2"),
        (Between(1, 3), "between 1 and 3"),
    ],
)
def test_valid_bounds_keep_their_description(bounds, description):
    assert bounds.describe() == description


def test_valid_bounds_keep_their_equality():
    assert Exactly(2) == CallBounds(minimum=2, maximum=2)
    assert AtLeast(2) == CallBounds(minimum=2)
    assert Exactly(2) != Exactly(3)


def test_depends_defaults_to_optional_and_unbounded():
    assert Depends(lookup_customer).bounds == CallBounds(minimum=0, maximum=None)


def test_required_stays_at_least_once():
    """Not exactly once: narrowing it would change what existing endpoints mean."""
    assert Required(lookup_customer).bounds == CallBounds(minimum=1, maximum=None)


def test_calls_tightens_the_marker():
    assert Required(lookup_customer, calls=Exactly(1)).bounds == CallBounds(1, 1)
    assert Depends(lookup_customer, calls=AtMost(2)).bounds == CallBounds(0, 2)


def test_calls_may_not_contradict_depends():
    with pytest.raises(ValueError, match="Use Required"):
        Depends(lookup_customer, calls=AtLeast(1))


def test_calls_may_not_contradict_required():
    with pytest.raises(ValueError, match=r"unsatisfiable|Use Depends"):
        Required(lookup_customer, calls=AtMost(0))


# --- integration with the endpoint ------------------------------------------


def test_an_operation_registers_like_a_bare_callable():
    contract = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )
    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        request: OrderRequest, customer=Required(contract)
    ) -> OrderResponse:
        """Place an order for this customer."""
        ...

    (tool,) = summon.endpoints[0].tools
    assert tool.name == "lookup_customer"
    assert tool.required is True
    assert tool.contract is contract
    assert tool.bounds == CallBounds(minimum=1)


def test_a_bare_callable_still_registers_with_no_contract():
    """The contract is opt-in; endpoints written before it keep working unchanged."""
    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        request: OrderRequest, customer=Required(lookup_customer)
    ) -> OrderResponse:
        """Place an order for this customer."""
        ...

    (tool,) = summon.endpoints[0].tools
    assert tool.contract is None
    assert tool.bounds == CallBounds(minimum=1)


def test_a_maximum_does_not_relax_required_below_once():
    """`calls` tightens the marker; it must never let a Required operation be skipped."""
    bounds = Required(lookup_customer, calls=AtMost(3)).bounds

    assert bounds == CallBounds(minimum=1, maximum=3)
    assert bounds.describe() == "between 1 and 3"


def test_a_maximum_leaves_depends_optional():
    assert Depends(lookup_customer, calls=AtMost(3)).bounds == CallBounds(0, 3)


# --- the bindings are the security boundary ----------------------------------


def test_registered_bindings_cannot_be_changed_through_the_contract():
    """`frozen=True` stops reassignment; it does not stop mutating the mapping.

    The endpoint stores this exact object, so a writable mapping would let the
    security boundary be moved after registration and after validation.
    """
    contract = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )

    with pytest.raises(TypeError):
        contract.bind["customer_id"] = AgentChoice()  # type: ignore[index]


def test_registered_bindings_cannot_be_changed_through_the_callers_mapping():
    """The contract snapshots the mapping rather than storing it by reference."""
    declared = {"customer_id": FromRequest("customer_id")}
    contract = Operation(lookup_customer, bind=declared, output=Customer)
    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        request: OrderRequest, customer=Required(contract)
    ) -> OrderResponse:
        """Place an order for this customer."""
        ...

    declared["customer_id"] = FromRequest("attacker_controlled")

    registered = summon.endpoints[0].tools[0].contract
    assert registered is not None
    assert registered.bind == {"customer_id": FromRequest("customer_id")}


def test_with_bind_returns_an_immutable_snapshot_too():
    contract = Operation(
        lookup_customer, bind={"customer_id": FromRequest("customer_id")}
    )
    derived = contract.with_bind(customer_id=FromRequest("account_id"))

    with pytest.raises(TypeError):
        derived.bind["customer_id"] = AgentChoice()  # type: ignore[index]
    assert contract.bind == {"customer_id": FromRequest("customer_id")}


# --- the public surface is complete ------------------------------------------


def test_call_bounds_is_importable_from_the_package_root():
    """The helpers cannot express every interval, so the type itself is public."""
    assert CallBounds(minimum=2, maximum=3).describe() == "between 2 and 3"
    assert Between(2, 3) == CallBounds(minimum=2, maximum=3)


def test_declared_ordering_cannot_be_changed_through_the_callers_sequence():
    """`after` is graph data, read exactly as the bindings are."""
    audit = Operation(lookup_customer)
    ordering = [audit]
    contract = Operation(place_order, after=ordering)

    ordering.append(Operation(lookup_customer))

    assert contract.after == (audit,)
    assert isinstance(contract.after, tuple)


# --- graph node semantics ----------------------------------------------------


def test_operations_are_hashable_whether_or_not_they_are_bound():
    """Step 03 uses these as set and dict keys; it cannot depend on `bind`."""
    unbound = Operation(lookup_customer)
    bound = Operation(lookup_customer, bind={"customer_id": FromRequest("customer_id")})
    ordered = Operation(place_order, after=[unbound])

    assert {unbound, bound, ordered} == {unbound, bound, ordered}
    assert len({unbound, bound, ordered}) == 3


def test_operations_are_distinct_nodes_even_when_declared_alike():
    """Two declarations are two nodes, so FromResult names one of them unambiguously."""
    first = Operation(lookup_customer, bind={"customer_id": FromRequest("customer_id")})
    second = Operation(
        lookup_customer, bind={"customer_id": FromRequest("customer_id")}
    )

    assert first == first
    assert first != second
    assert FromResult(first, "tier") == FromResult(first, "tier")
    assert FromResult(first, "tier") != FromResult(second, "tier")
