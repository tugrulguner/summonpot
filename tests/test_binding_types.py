"""Conservative type checking of bound arguments.

The rule is asymmetric on purpose: a binding is rejected only when it can be *proven*
wrong. Anything unresolved, `Any`, or a shape the comparison does not model is
accepted, because a guard that refuses a valid declaration is worse than one that
misses an invalid one — the invalid one still fails later with a real error, while
the valid one can never be written at all.

The acceptance tests here matter as much as the rejections.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol

import pytest
from pydantic import BaseModel, Field

from summonpot import (
    AgentChoice,
    Exactly,
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot._validation import (
    _is_compatible as is_compatible,
)
from summonpot._validation import (
    _selectable_item_type as selectable_item_type,
)


class Person(BaseModel):
    name: str


class Customer(Person):
    tier: str


class Request(BaseModel):
    customer_id: str
    quantity: int
    ratio: float
    tags: list[str]
    anything: Any
    optional_note: str | None = None


class Response(BaseModel):
    ok: bool


def _register(summon: Summon, *contracts: Operation) -> None:
    """Register an endpoint declaring the given contracts."""
    import inspect as _inspect

    def endpoint(request: Request, **_: object) -> Response:
        """Do the thing."""
        ...

    params = [
        _inspect.Parameter(
            "request", _inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
        )
    ]
    params += [
        _inspect.Parameter(
            f"op{index}",
            _inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Required(
                contract, calls=Exactly(1) if len(contracts) == 1 else None
            ),
            annotation=object,
        )
        for index, contract in enumerate(contracts)
    ]
    endpoint.__signature__ = _inspect.Signature(  # type: ignore[attr-defined]
        params, return_annotation=Response
    )
    endpoint.__annotations__ = {"request": Request, "return": Response}
    summon("/thing")(endpoint)


# --- the comparison itself ---------------------------------------------------


@pytest.mark.parametrize(
    ("supplied", "wanted", "compatible"),
    [
        (str, str, True),
        (int, str, False),
        (Customer, Person, True),
        (Person, Customer, False),
        (int, float, True),
        (bool, int, True),
        (float, int, False),
        (str, str | None, True),
        (int | str, str, False),
        (str | None, str | None, True),
        (list[int], list[int], True),
        (list[int], list[str], False),
        (list[int], Sequence[int], True),
        (Literal["a", "b"], str, True),
        (Literal[1], str, False),
    ],
)
def test_provable_relationships(supplied, wanted, compatible):
    assert is_compatible(supplied, wanted) is compatible


@pytest.mark.parametrize(
    ("supplied", "wanted"),
    [
        (Any, str),
        (str, Any),
        (None, str),
        (str, None),
        ("UnresolvedName", str),
        (str, "UnresolvedName"),
        (object, int),
        (Annotated[str, Field(min_length=3)], str),
        (str, Annotated[str, Field(min_length=3)]),
    ],
    ids=[
        "any-source",
        "any-target",
        "unannotated-source",
        "unannotated-target",
        "forward-ref-source",
        "forward-ref-target",
        "object",
        "annotated-source",
        "annotated-target",
    ],
)
def test_the_unprovable_is_accepted(supplied, wanted):
    """Not proven wrong is not the same as proven right, and only the first rejects."""
    assert is_compatible(supplied, wanted) is True


# --- bindings, end to end ----------------------------------------------------


def wants_str(customer_id: str) -> Customer:
    """Take a string."""
    return Customer(name="n", tier="t")


def wants_int(quantity: int) -> Customer:
    """Take an integer."""
    return Customer(name="n", tier="t")


def test_a_request_field_of_the_wrong_type_is_rejected():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            Operation(
                wants_str,
                bind={"customer_id": FromRequest("quantity")},
                output=Customer,
            ),
        )


def test_a_request_field_of_the_right_type_is_accepted():
    summon = Summon("svc")

    _register(
        summon,
        Operation(
            wants_str, bind={"customer_id": FromRequest("customer_id")}, output=Customer
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


def test_a_widening_request_field_is_accepted():
    """int satisfies float; the numeric tower is not a mismatch."""

    def wants_float(ratio: float) -> Customer:
        """Take a float."""
        return Customer(name="n", tier="t")

    summon = Summon("svc")

    _register(
        summon,
        Operation(
            wants_float, bind={"ratio": FromRequest("quantity")}, output=Customer
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


def test_an_untyped_request_field_is_accepted():
    """`Any` proves nothing, so it cannot disprove anything either."""
    summon = Summon("svc")

    _register(
        summon,
        Operation(
            wants_str, bind={"customer_id": FromRequest("anything")}, output=Customer
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


def test_a_result_field_of_the_wrong_type_is_rejected():
    producer = Operation(
        wants_str, bind={"customer_id": FromRequest("customer_id")}, output=Customer
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": FromResult(producer, "tier")},
                output=Customer,
            ),
        )


def test_a_compatible_result_chain_reaches_fail_closed_admission():
    def consume_tier(customer_id: str) -> Customer:
        """Take a string."""
        return Customer(name="n", tier="t")

    producer = Operation(
        wants_str, bind={"customer_id": FromRequest("customer_id")}, output=Customer
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                consume_tier,
                bind={"customer_id": FromResult(producer, "tier")},
                output=Customer,
            ),
        )


def test_a_context_binding_reaches_fail_closed_admission():
    """Its type is not disproven, but the current runtime cannot enforce its source."""
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            Operation(
                wants_str,
                bind={"customer_id": FromContext("trace_id")},
                output=Customer,
            ),
        )


# --- what a model may be asked to choose from --------------------------------


@pytest.mark.parametrize(
    ("output", "selectable"),
    [
        (list[Customer], True),
        (set[str], True),
        (tuple[str, ...], True),
        (Sequence[str], True),
        (str, False),
        (bytes, False),
        (dict[str, int], False),
        (Customer, False),
        (Any, True),
    ],
)
def test_selectable_shapes(output, selectable):
    assert selectable_item_type(output)[0] is selectable


def test_a_valid_result_backed_choice_reaches_fail_closed_admission():
    def list_tiers(customer_id: str) -> list[str]:
        """List tiers."""
        return ["a"]

    producer = Operation(
        list_tiers, bind={"customer_id": FromRequest("customer_id")}, output=list[str]
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                wants_str,
                bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


def test_a_choice_whose_item_type_contradicts_the_collection_is_rejected():
    def list_tiers(customer_id: str) -> list[str]:
        """List tiers."""
        return ["a"]

    producer = Operation(
        list_tiers, bind={"customer_id": FromRequest("customer_id")}, output=list[str]
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="returns a collection of"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer, item_type=int)},
                output=Customer,
            ),
        )


# --- relations the first pass got wrong --------------------------------------


@pytest.mark.parametrize(
    ("supplied", "wanted", "compatible"),
    [
        # A related origin says nothing about the parameters.
        (list[int], Sequence[str], False),
        (list[int], Sequence[int], True),
        (dict[str, int], Mapping[str, str], False),
        (dict[str, int], Mapping[str, int], True),
        # A literal target constrains values, but its value *types* are provable.
        (int, Literal["x"], False),
        (str, Literal["x"], True),
        (Literal["z"], Literal["x", "y"], False),
        (Literal["x"], Literal["x", "y"], True),
        # bool is an int, so it widens like one.
        (bool, float, True),
        (bool, complex, True),
    ],
)
def test_relations_that_needed_correcting(supplied, wanted, compatible):
    assert is_compatible(supplied, wanted) is compatible


def test_an_uncheckable_relation_is_unknown_not_a_crash():
    """`issubclass` raises for a Protocol that is not runtime_checkable."""

    class Plain(Protocol):
        def go(self) -> None: ...

    assert is_compatible(int, Plain) is True


def test_a_protocol_argument_registers():
    """The crash reached registration, so the regression belongs there too."""

    class Plain(Protocol):
        def go(self) -> None: ...

    def wants_protocol(customer_id: Plain) -> Customer:
        """Take a protocol."""
        return Customer(name="n", tier="t")

    summon = Summon("svc")

    _register(
        summon,
        Operation(
            wants_protocol,
            bind={"customer_id": FromRequest("customer_id")},
            output=Customer,
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


@pytest.mark.parametrize(
    ("output", "selectable"),
    [
        (tuple[str, ...], True),
        (tuple[int, str], False),
        (tuple[int], False),
        (tuple[()], False),
        (tuple, True),
    ],
    ids=["homogeneous", "heterogeneous", "fixed-one", "empty", "bare"],
)
def test_only_a_homogeneous_tuple_is_selectable(output, selectable):
    """A fixed tuple has a different type per position, so there is no item type."""
    assert selectable_item_type(output)[0] is selectable


# --- the chosen value has to fit the argument receiving it -------------------


def _tier_producer() -> Operation:
    def list_tiers(customer_id: str) -> list[str]:
        """List tiers."""
        return ["standard"]

    return Operation(
        list_tiers, bind={"customer_id": FromRequest("customer_id")}, output=list[str]
    )


def test_a_declared_item_type_must_fit_the_argument():
    producer = _tier_producer()
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


def test_an_inferred_item_type_must_fit_the_argument():
    """With no explicit item_type, the collection's element type is the choice."""
    producer = _tier_producer()
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )


def test_a_direct_choice_must_also_fit_the_argument():
    """A choice with no producer behind it was skipping type validation entirely."""
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(item_type=str)},
                output=Customer,
            ),
        )


def test_an_unconstrained_choice_is_still_accepted():
    """Nothing declares the type, so nothing can be disproven."""
    summon = Summon("svc")

    _register(
        summon,
        Operation(wants_int, bind={"quantity": AgentChoice()}, output=Customer),
    )

    assert summon.endpoints[0].tools[0].contract is not None


def test_a_choice_that_fits_reaches_fail_closed_admission():
    producer = _tier_producer()
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                wants_str,
                bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


# --- an unknown item_type must not erase what the producer proved ------------


@pytest.mark.parametrize("item_type", [Any, object], ids=["any", "object"])
def test_an_unknown_item_type_does_not_mask_the_producer(item_type):
    """The model can only pick values the producer returned, so its element type
    is a fact that a broader `item_type` cannot widen away."""
    producer = _tier_producer()
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={
                    "quantity": AgentChoice(from_result=producer, item_type=item_type)
                },
                output=Customer,
            ),
        )


def test_an_unparameterised_producer_falls_back_to_the_item_type():
    """With no element type to read, the declaration is the only thing that says."""

    def list_anything(customer_id: str) -> list:
        """List values."""
        return []

    producer = Operation(
        list_anything, bind={"customer_id": FromRequest("customer_id")}, output=list
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


def test_an_unparameterised_valid_choice_reaches_fail_closed_admission():
    def list_anything(customer_id: str) -> list:
        """List values."""
        return []

    producer = Operation(
        list_anything, bind={"customer_id": FromRequest("customer_id")}, output=list
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )


# --- a fixed tuple against a homogeneous one ---------------------------------


@pytest.mark.parametrize(
    ("supplied", "compatible"),
    [
        (tuple[int, str], False),
        (tuple[int, int], True),
        (tuple[()], True),
        (tuple, True),
        (tuple[int, ...], True),
    ],
    ids=["heterogeneous", "homogeneous-fixed", "empty", "bare", "variadic"],
)
def test_a_fixed_tuple_against_a_homogeneous_target(supplied, compatible):
    """A differing parameter count is not unknown when the target admits any number:
    every member the source declares still has to satisfy the one element type."""
    assert is_compatible(supplied, tuple[int, ...]) is compatible


@pytest.mark.parametrize(
    ("supplied", "wanted", "compatible"),
    [
        # A fixed tuple is a sequence of its members, so a homogeneous target is
        # satisfied only when every member fits its one element type.
        (tuple[int, str], Sequence[int], False),
        (tuple[int, int], Sequence[int], True),
        (list[int], Sequence[int], True),
        # Two fixed tuples describe positions, so their lengths have to agree.
        (tuple[int, str], tuple[int], False),
        (tuple[int], tuple[int, str], False),
        (tuple[int, str], tuple[int, str], True),
        # Unresolved shapes stay unknown.
        (tuple[()], tuple[int, ...], True),
        (tuple, tuple[int, ...], True),
    ],
)
def test_fixed_tuple_relations(supplied, wanted, compatible):
    assert is_compatible(supplied, wanted) is compatible


# --- a union of collections is still something to choose from ----------------


@pytest.mark.parametrize(
    ("output", "selectable", "element"),
    [
        (list[str] | set[str], True, str),
        (list[str] | tuple[str, ...], True, str),
        # Members disagree, so the element stays a union rather than being erased;
        # the consumer check then still applies to whatever is picked.
        (list[str] | list[int], True, str | int),
        # A scalar may arrive, so the whole thing is not selectable.
        (list[str] | str, False, None),
        (list[str] | None, False, None),
        # An unknown member cannot be disproven.
        (list[str] | Any, True, str | Any),
    ],
    ids=[
        "same-element",
        "different-shapes",
        "differing-elements",
        "mixed-scalar",
        "optional",
        "unknown-member",
    ],
)
def test_a_union_output_is_selectable_when_every_member_is(output, selectable, element):
    assert selectable_item_type(output) == (selectable, element)


def test_a_valid_union_choice_reaches_fail_closed_admission():
    """The type relation is valid, but result-backed execution is not shipped."""

    def list_tiers(customer_id: str) -> list[str] | set[str]:
        """List tiers."""
        return ["standard"]

    producer = Operation(
        list_tiers,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | set[str],
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                wants_str,
                bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


def test_a_choice_from_a_union_containing_a_scalar_is_rejected():
    def list_tiers(customer_id: str) -> list[str] | str:
        """List tiers."""
        return ["standard"]

    producer = Operation(
        list_tiers,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | str,
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="not a collection of selectable items"):
        _register(
            summon,
            producer,
            Operation(
                wants_str,
                bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


@pytest.mark.parametrize(
    ("supplied", "wanted", "compatible"),
    [
        # `tuple[()]` is a known arity of zero, unlike bare `tuple`.
        (tuple[()], tuple[int], False),
        (tuple[int], tuple[()], False),
        (tuple[()], tuple[()], True),
        # A variadic source admits lengths a fixed target cannot accept.
        (tuple[int, ...], tuple[int], False),
        (tuple[int, ...], tuple[int, str], False),
        (tuple[int, ...], tuple[int, ...], True),
        # An empty source satisfies a homogeneous target vacuously.
        (tuple[()], tuple[int, ...], True),
        # Bare tuple stays unknown.
        (tuple, tuple[int], True),
    ],
)
def test_tuple_arity_relations(supplied, wanted, compatible):
    assert is_compatible(supplied, wanted) is compatible


@pytest.mark.parametrize(
    ("output", "selectable", "element"),
    [
        # Differing element types stay a union, so the source-union rule still
        # applies to whatever the model picks.
        (list[str] | list[int], True, str | int),
        (list[str] | set[int], True, str | int),
        (list[str] | set[str], True, str),
        # A known non-selectable member rejects wherever it appears in the union.
        (list[str] | Any | str, False, None),
        (list[str] | str | Any, False, None),
        (list[str] | Any, True, str | Any),
    ],
    ids=[
        "differing-elements",
        "differing-shapes-and-elements",
        "same-element",
        "scalar-after-unknown",
        "scalar-before-unknown",
        "unknown-only",
    ],
)
def test_union_selection_is_order_independent(output, selectable, element):
    assert selectable_item_type(output) == (selectable, element)


def test_a_choice_of_differing_elements_must_still_fit_the_argument():
    """Collapsing the possibilities to unknown hid a provable mismatch."""

    def mixed_values(customer_id: str) -> list[str] | list[int]:
        """Return values of either type."""
        return []

    producer = Operation(
        mixed_values,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | list[int],
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )


def test_a_choice_of_differing_elements_reaches_fail_closed_admission():
    def mixed_values(customer_id: str) -> list[str] | list[int]:
        """Return values of either type."""
        return []

    def accepts_either(quantity: int | str) -> Customer:
        """Take either."""
        return Customer(name="n", tier="t")

    producer = Operation(
        mixed_values,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | list[int],
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                accepts_either,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )


def test_a_variadic_source_cannot_satisfy_an_empty_fixed_tuple():
    """`tuple[()]` is a fixed target of arity zero like any other fixed arity."""
    assert is_compatible(tuple[int, ...], tuple[()]) is False
    assert is_compatible(tuple[()], tuple[int, ...]) is True
    assert is_compatible(tuple, tuple[()]) is True


@pytest.mark.parametrize(
    ("output", "element"),
    [
        (list[str] | Any, str | Any),
        (list[str] | list, str | Any),
        (list[int] | Any, int | Any),
    ],
    ids=["unknown-member", "unparameterised-member", "compatible-known-member"],
)
def test_an_unknown_possibility_joins_the_known_ones(output, element):
    """Adding an unknown branch must not erase what the known branches proved."""
    assert selectable_item_type(output) == (True, element)


def test_a_known_incompatible_possibility_survives_an_unknown_branch():
    def maybe_values(customer_id: str) -> list[str] | Any:
        """Return values."""
        return []

    producer = Operation(
        maybe_values,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | Any,
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )


def test_a_compatible_known_possibility_reaches_fail_closed_admission():
    def maybe_values(customer_id: str) -> list[int] | Any:
        """Return values."""
        return []

    producer = Operation(
        maybe_values,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[int] | Any,
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):
        _register(
            summon,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )
