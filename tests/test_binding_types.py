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
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Pot,
    Required,
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


def _register(pot: Pot, *contracts: Operation) -> None:
    """Register an endpoint declaring the given contracts."""
    import inspect as _inspect

    def endpoint(request: Request, **_: object) -> Response:
        """Do the thing."""
        raise NotImplementedError

    params = [
        _inspect.Parameter(
            "request", _inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
        )
    ]
    params += [
        _inspect.Parameter(
            f"op{index}",
            _inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Required(contract),
            annotation=object,
        )
        for index, contract in enumerate(contracts)
    ]
    endpoint.__signature__ = _inspect.Signature(  # type: ignore[attr-defined]
        params, return_annotation=Response
    )
    endpoint.__annotations__ = {"request": Request, "return": Response}
    pot.summon("/thing")(endpoint)


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
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
            Operation(
                wants_str,
                bind={"customer_id": FromRequest("quantity")},
                output=Customer,
            ),
        )


def test_a_request_field_of_the_right_type_is_accepted():
    pot = Pot("svc")

    _register(
        pot,
        Operation(
            wants_str, bind={"customer_id": FromRequest("customer_id")}, output=Customer
        ),
    )

    assert pot.endpoints[0].tools[0].contract is not None


def test_a_widening_request_field_is_accepted():
    """int satisfies float; the numeric tower is not a mismatch."""

    def wants_float(ratio: float) -> Customer:
        """Take a float."""
        return Customer(name="n", tier="t")

    pot = Pot("svc")

    _register(
        pot,
        Operation(
            wants_float, bind={"ratio": FromRequest("quantity")}, output=Customer
        ),
    )

    assert pot.endpoints[0].tools[0].contract is not None


def test_an_untyped_request_field_is_accepted():
    """`Any` proves nothing, so it cannot disprove anything either."""
    pot = Pot("svc")

    _register(
        pot,
        Operation(
            wants_str, bind={"customer_id": FromRequest("anything")}, output=Customer
        ),
    )

    assert pot.endpoints[0].tools[0].contract is not None


def test_a_result_field_of_the_wrong_type_is_rejected():
    producer = Operation(
        wants_str, bind={"customer_id": FromRequest("customer_id")}, output=Customer
    )
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
            producer,
            Operation(
                wants_int,
                bind={"quantity": FromResult(producer, "tier")},
                output=Customer,
            ),
        )


def test_a_result_field_of_the_right_type_is_accepted():
    def consume_tier(customer_id: str) -> Customer:
        """Take a string."""
        return Customer(name="n", tier="t")

    producer = Operation(
        wants_str, bind={"customer_id": FromRequest("customer_id")}, output=Customer
    )
    pot = Pot("svc")

    _register(
        pot,
        producer,
        Operation(
            consume_tier,
            bind={"customer_id": FromResult(producer, "tier")},
            output=Customer,
        ),
    )

    assert len(pot.endpoints[0].tools) == 2


def test_a_context_binding_is_never_rejected():
    """Framework context has no type registry, so nothing about it is provable."""
    pot = Pot("svc")

    _register(
        pot,
        Operation(
            wants_str, bind={"customer_id": FromContext("trace_id")}, output=Customer
        ),
    )

    assert pot.endpoints[0].tools[0].contract is not None


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


def test_a_choice_from_a_collection_is_accepted():
    def list_tiers(customer_id: str) -> list[str]:
        """List tiers."""
        return ["a"]

    producer = Operation(
        list_tiers, bind={"customer_id": FromRequest("customer_id")}, output=list[str]
    )
    pot = Pot("svc")

    _register(
        pot,
        producer,
        Operation(
            wants_str,
            bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
            output=Customer,
        ),
    )

    assert len(pot.endpoints[0].tools) == 2


def test_a_choice_whose_item_type_contradicts_the_collection_is_rejected():
    def list_tiers(customer_id: str) -> list[str]:
        """List tiers."""
        return ["a"]

    producer = Operation(
        list_tiers, bind={"customer_id": FromRequest("customer_id")}, output=list[str]
    )
    pot = Pot("svc")

    with pytest.raises(TypeError, match="returns a collection of"):
        _register(
            pot,
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

    pot = Pot("svc")

    _register(
        pot,
        Operation(
            wants_protocol,
            bind={"customer_id": FromRequest("customer_id")},
            output=Customer,
        ),
    )

    assert pot.endpoints[0].tools[0].contract is not None


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
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
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
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer)},
                output=Customer,
            ),
        )


def test_a_direct_choice_must_also_fit_the_argument():
    """A choice with no producer behind it was skipping type validation entirely."""
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(item_type=str)},
                output=Customer,
            ),
        )


def test_an_unconstrained_choice_is_still_accepted():
    """Nothing declares the type, so nothing can be disproven."""
    pot = Pot("svc")

    _register(
        pot,
        Operation(wants_int, bind={"quantity": AgentChoice()}, output=Customer),
    )

    assert pot.endpoints[0].tools[0].contract is not None


def test_a_choice_that_fits_is_accepted():
    producer = _tier_producer()
    pot = Pot("svc")

    _register(
        pot,
        producer,
        Operation(
            wants_str,
            bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
            output=Customer,
        ),
    )

    assert len(pot.endpoints[0].tools) == 2


# --- an unknown item_type must not erase what the producer proved ------------


@pytest.mark.parametrize("item_type", [Any, object], ids=["any", "object"])
def test_an_unknown_item_type_does_not_mask_the_producer(item_type):
    """The model can only pick values the producer returned, so its element type
    is a fact that a broader `item_type` cannot widen away."""
    producer = _tier_producer()
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
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
    pot = Pot("svc")

    with pytest.raises(TypeError, match="incompatible"):
        _register(
            pot,
            producer,
            Operation(
                wants_int,
                bind={"quantity": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )


def test_an_unparameterised_producer_with_no_item_type_is_accepted():
    def list_anything(customer_id: str) -> list:
        """List values."""
        return []

    producer = Operation(
        list_anything, bind={"customer_id": FromRequest("customer_id")}, output=list
    )
    pot = Pot("svc")

    _register(
        pot,
        producer,
        Operation(
            wants_int,
            bind={"quantity": AgentChoice(from_result=producer)},
            output=Customer,
        ),
    )

    assert len(pot.endpoints[0].tools) == 2


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
        # Every member is selectable but they disagree, so the element is unknown.
        (list[str] | list[int], True, None),
        # A scalar may arrive, so the whole thing is not selectable.
        (list[str] | str, False, None),
        (list[str] | None, False, None),
        # An unknown member cannot be disproven.
        (list[str] | Any, True, None),
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


def test_a_choice_from_a_union_of_collections_is_accepted():
    """Rejecting this was a false rejection: every possible output is a collection."""

    def list_tiers(customer_id: str) -> list[str] | set[str]:
        """List tiers."""
        return ["standard"]

    producer = Operation(
        list_tiers,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | set[str],
    )
    pot = Pot("svc")

    _register(
        pot,
        producer,
        Operation(
            wants_str,
            bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
            output=Customer,
        ),
    )

    assert len(pot.endpoints[0].tools) == 2


def test_a_choice_from_a_union_containing_a_scalar_is_rejected():
    def list_tiers(customer_id: str) -> list[str] | str:
        """List tiers."""
        return ["standard"]

    producer = Operation(
        list_tiers,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str] | str,
    )
    pot = Pot("svc")

    with pytest.raises(TypeError, match="not a collection of selectable items"):
        _register(
            pot,
            producer,
            Operation(
                wants_str,
                bind={"customer_id": AgentChoice(from_result=producer, item_type=str)},
                output=Customer,
            ),
        )
