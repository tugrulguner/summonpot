"""Registration-time validation of typed capability contracts.

Step 02: a contract that cannot be satisfied fails when the endpoint is declared,
not part-way through a request. Half of these tests assert that a *valid* declaration
is still accepted, because every guard this project has added needed that as much as
it needed the rejection case.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import BaseModel

from summonpot import (
    AgentChoice,
    AtLeast,
    AtMost,
    Depends,
    Exactly,
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)


class OrderRequest(BaseModel):
    customer_id: str
    sku: str


class Customer(BaseModel):
    customer_id: str
    tier: str


class OrderResponse(BaseModel):
    order_id: str


def lookup_customer(customer_id: str) -> Customer:
    """Look up a customer."""
    return Customer(customer_id=customer_id, tier="standard")


def place_order(customer_id: str, tier: str, sku: str) -> OrderResponse:
    """Place an order."""
    return OrderResponse(order_id="o1")


def record_audit(customer_id: str) -> Customer:
    """Record an audit entry."""
    return Customer(customer_id=customer_id, tier="standard")


# --- valid declarations are still accepted -----------------------------------


@pytest.mark.parametrize(
    "dependency", [Depends(lookup_customer), Required(lookup_customer)]
)
def test_a_bare_callable_with_implicit_marker_bounds_needs_no_contract(dependency):
    """Legacy Depends(fn) and Required(fn) endpoints keep working unchanged."""
    summon = Summon("svc")

    @summon("/orders")
    def create_order(request: OrderRequest, customer=dependency) -> OrderResponse:
        """Place an order."""
        ...

    assert summon.endpoints[0].tools[0].contract is None


def test_a_copied_legacy_tool_cannot_disguise_changed_bounds_as_implicit():
    source = Summon("source")

    @source("/source")
    def source_endpoint(
        request: OrderRequest, customer=Required(lookup_customer)
    ) -> OrderResponse:
        """Load one customer through the legacy path."""
        ...

    forged = replace(source.endpoints[0].tools[0], bounds=Exactly(2))
    summon = Summon("svc", tools=[forged])

    with pytest.raises(TypeError, match="cannot enforce the declared call bound"):

        @summon("/orders")
        def create_order(request: OrderRequest) -> OrderResponse:
            """Place an order."""
            ...


def test_an_unchanged_copy_of_a_legacy_tool_keeps_implicit_marker_bounds():
    source = Summon("source")

    @source("/source")
    def source_endpoint(
        request: OrderRequest, customer=Required(lookup_customer)
    ) -> OrderResponse:
        """Load one customer through the legacy path."""
        ...

    copied = replace(source.endpoints[0].tools[0])
    summon = Summon("svc", tools=[copied])

    @summon("/orders")
    def create_order(request: OrderRequest) -> OrderResponse:
        """Place an order."""
        ...

    assert summon.endpoints[0].tools[0].bounds == copied.bounds


def test_a_bare_operation_contract_is_rejected_instead_of_using_the_legacy_path():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(Operation(lookup_customer)),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_an_output_contract_without_enforceable_bindings_is_rejected():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(Operation(lookup_customer, output=Customer)),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_a_complete_chain_is_rejected_until_multi_operation_execution_ships():
    lookup = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(lookup),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(lookup, "tier"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_direct_agent_choice_is_accepted_by_the_enforced_slice():
    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        request: OrderRequest,
        customer=Required(
            Operation(
                lookup_customer,
                bind={"customer_id": AgentChoice()},
                output=Customer,
            ),
            calls=Exactly(1),
        ),
    ) -> OrderResponse:
        """Place an order."""
        ...

    assert summon.endpoints[0].tools[0].contract is not None


def test_from_context_is_rejected_until_context_injection_ships():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    lookup_customer,
                    bind={"customer_id": FromContext("user_id")},
                    output=Customer,
                ),
                calls=Exactly(1),
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_from_request_resolves_against_a_scalar_endpoint():
    """An endpoint without a request model still declares bindable field names."""
    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        customer_id: str,
        customer=Required(
            Operation(
                lookup_customer,
                bind={"customer_id": FromRequest("customer_id")},
                output=Customer,
            ),
            calls=Exactly(1),
        ),
    ) -> str:
        """Place an order."""
        ...

    assert summon.endpoints[0].tools[0].contract is not None


def test_a_diamond_of_dependencies_is_not_a_cycle():
    """Two operations may share a predecessor."""
    first = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )
    second = Operation(
        record_audit,
        bind={"customer_id": FromResult(first, "customer_id")},
        output=Customer,
    )
    third = Operation(
        place_order,
        bind={
            "customer_id": FromResult(first, "customer_id"),
            "tier": FromResult(first, "tier"),
            "sku": FromRequest("sku"),
        },
        output=OrderResponse,
        after=[second],
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            a=Required(first),
            b=Required(second),
            c=Required(third),
        ) -> OrderResponse:
            """Place an order."""
            ...


# --- invalid declarations fail at registration -------------------------------


def test_a_binding_source_outside_the_closed_vocabulary_is_rejected():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="binding source must be one of"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    lookup_customer,
                    bind={"customer_id": object()},  # type: ignore[dict-item]
                    output=Customer,
                ),
                calls=Exactly(1),
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


@pytest.mark.parametrize(
    "source",
    [
        type("RequestSourceSubclass", (FromRequest,), {})("customer_id"),
        type("ResultSourceSubclass", (FromResult,), {})(
            Operation(lookup_customer, output=Customer), "customer_id"
        ),
        type("ContextSourceSubclass", (FromContext,), {})("principal"),
        type("ChoiceSourceSubclass", (AgentChoice,), {})(),
    ],
    ids=["request", "result", "context", "choice"],
)
def test_a_binding_source_subclass_is_outside_the_exact_vocabulary(source):
    summon = Summon("svc")

    with pytest.raises(TypeError, match="binding source must be one of"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    lookup_customer,
                    bind={"customer_id": source},
                    output=Customer,
                ),
                calls=Exactly(1),
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_each_runtime_supported_binding_source_is_accepted():
    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        request: OrderRequest,
        customer=Required(
            Operation(
                search_customers,
                bind={
                    "query": FromRequest("customer_id"),
                    "limit": AgentChoice(),
                },
                output=Customer,
            ),
            calls=Exactly(1),
        ),
    ) -> OrderResponse:
        """Place an order."""
        ...

    assert summon.endpoints[0].tools[0].contract is not None


@pytest.mark.parametrize(
    "dependency",
    [
        Required(lookup_customer, calls=AtLeast(2)),
        Required(lookup_customer, calls=Exactly(1)),
        Depends(lookup_customer, calls=AtMost(1)),
    ],
    ids=["broader-required", "uncontracted-exact", "optional-maximum"],
)
def test_an_unenforceable_explicit_call_bound_is_rejected(dependency):
    summon = Summon("svc")

    with pytest.raises(TypeError, match="cannot enforce the declared call bound"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=dependency,
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_a_second_capability_cannot_disable_an_existing_operation_contract():
    summon = Summon("svc", tools=[record_audit])

    with pytest.raises(TypeError, match="would leave its explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    lookup_customer,
                    bind={"customer_id": FromRequest("customer_id")},
                    output=Customer,
                ),
                calls=Exactly(1),
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_a_binding_for_an_unknown_argument_is_rejected():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="takes no such argument"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    lookup_customer,
                    bind={"custmer_id": FromRequest("customer_id")},
                    output=Customer,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_a_partially_bound_operation_is_rejected():
    """An omitted argument must not silently become model-controlled."""
    summon = Summon("svc")

    with pytest.raises(TypeError, match="unbound"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            order=Required(
                Operation(
                    place_order,
                    bind={"customer_id": FromRequest("customer_id")},
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_from_request_naming_a_missing_field_is_rejected():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="request does not declare"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    lookup_customer,
                    bind={"customer_id": FromRequest("custmer_id")},
                    output=Customer,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_from_result_on_an_undeclared_operation_is_rejected():
    elsewhere = Operation(lookup_customer, output=Customer)
    summon = Summon("svc")

    with pytest.raises(TypeError, match="does not declare"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(elsewhere, "tier"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_from_result_on_an_operation_without_an_output_is_rejected():
    """A result cannot be read before it can be validated."""
    lookup = Operation(
        lookup_customer, bind={"customer_id": FromRequest("customer_id")}
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="declares no output type"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(lookup),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(lookup, "tier"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_from_result_naming_a_missing_output_field_is_rejected():
    lookup = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="Customer does not declare"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(lookup),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(lookup, "teir"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


# --- arguments the caller need not supply ------------------------------------


def search_customers(query: str, limit: int = 10) -> Customer:
    """Search customers."""
    return Customer(customer_id=query, tier="standard")


def flexible_lookup(customer_id: str, **extra: object) -> Customer:
    """Look up a customer, accepting extra keywords."""
    return Customer(customer_id=customer_id, tier="standard")


def _register(summon: Summon, contract: Operation) -> None:
    @summon("/orders")
    def create_order(
        request: OrderRequest, op=Required(contract, calls=Exactly(1))
    ) -> OrderResponse:
        """Place an order."""
        ...


def test_an_argument_with_a_default_may_be_left_unbound():
    """It is already determined: it takes the default and is not offered to the model."""
    summon = Summon("svc")

    _register(
        summon,
        Operation(
            search_customers,
            bind={"query": FromRequest("customer_id")},
            output=Customer,
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


def test_an_argument_with_a_default_may_still_be_bound_explicitly():
    summon = Summon("svc")

    _register(
        summon,
        Operation(
            search_customers,
            bind={"query": FromRequest("customer_id"), "limit": AgentChoice()},
            output=Customer,
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


def test_an_argument_without_a_default_still_has_to_be_bound():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="no default"):
        _register(
            summon,
            Operation(
                place_order,
                bind={"customer_id": FromRequest("customer_id")},
                output=OrderResponse,
            ),
        )


def test_an_operation_without_kwargs_still_rejects_an_unknown_binding():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="takes no such argument"):
        _register(
            summon,
            Operation(
                search_customers,
                bind={"query": FromRequest("customer_id"), "nope": AgentChoice()},
                output=Customer,
            ),
        )


def test_a_bound_method_operation_is_accepted():
    """The receiver is already supplied, so it is not an unbound argument."""

    class Directory:
        def __init__(self, tier: str) -> None:
            self.tier = tier

        def lookup(self, customer_id: str) -> Customer:
            """Look up a customer."""
            return Customer(customer_id=customer_id, tier=self.tier)

    summon = Summon("svc")

    _register(
        summon,
        Operation(
            Directory("gold").lookup,
            bind={"customer_id": FromRequest("customer_id")},
            output=Customer,
        ),
    )

    assert summon.endpoints[0].tools[0].contract is not None


# --- the capability set is closed --------------------------------------------


def test_after_may_only_name_a_declared_operation():
    """Ordering is part of the graph, so it cannot reach outside the endpoint."""
    elsewhere = Operation(lookup_customer, output=Customer)
    summon = Summon("svc")

    with pytest.raises(TypeError, match="orders itself after"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": AgentChoice(),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                    after=[elsewhere],
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_agent_choice_may_only_offer_results_of_a_declared_operation():
    elsewhere = Operation(lookup_customer, output=Customer)
    summon = Summon("svc")

    with pytest.raises(TypeError, match="offers"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": AgentChoice(from_result=elsewhere),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_after_naming_a_declared_operation_reaches_fail_closed_admission():
    lookup = Operation(
        lookup_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=Customer,
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(lookup),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(lookup, "tier"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                    after=[lookup],
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


# --- a result must be structured to be read from -----------------------------


def list_tiers(customer_id: str) -> list[str]:
    """List the tiers available to a customer."""
    return ["standard", "gold"]


def scalar_lookup(customer_id: str) -> str:
    """Return a customer tier."""
    return "standard"


def test_a_field_cannot_be_read_from_an_unstructured_result():
    """`output=str` has no statically checkable fields, so the read is unverifiable."""
    producer = Operation(
        scalar_lookup, bind={"customer_id": FromRequest("customer_id")}, output=str
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="cannot be checked"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            tier=Required(producer),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(producer, "anything"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


# --- a contracted operation has explicit parameters --------------------------


@pytest.mark.parametrize(
    "operation",
    [
        lambda customer_id, **extra: Customer(customer_id=customer_id, tier="t"),
        lambda *positional: Customer(customer_id="c", tier="t"),
    ],
    ids=["kwargs", "args"],
)
def test_a_contracted_operation_may_not_be_variadic(operation):
    """A variadic schema is open-ended, so the model could pass unnamed arguments."""
    operation.__doc__ = "Look up a customer."
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit parameters"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(
                Operation(
                    operation,
                    bind={"customer_id": FromRequest("customer_id")},
                    output=Customer,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_a_bare_variadic_callable_is_still_allowed():
    """Only a contract requires explicit parameters; legacy callables are untouched."""

    def flexible(**extra: object) -> Customer:
        """Look up a customer."""
        return Customer(customer_id="c", tier="t")

    summon = Summon("svc")

    @summon("/orders")
    def create_order(
        request: OrderRequest, customer=Required(flexible)
    ) -> OrderResponse:
        """Place an order."""
        ...

    assert summon.endpoints[0].tools[0].contract is None


# --- a result reaching the model must be validatable --------------------------


def test_agent_choice_may_not_offer_a_result_with_no_declared_output():
    """Offering a result puts it in agent context, so it must be validatable first."""
    producer = Operation(
        lookup_customer, bind={"customer_id": FromRequest("customer_id")}
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="declares no output type"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(producer),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": AgentChoice(from_result=producer, item_type=str),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_valid_result_backed_agent_choice_reaches_fail_closed_admission():
    producer = Operation(
        list_tiers,
        bind={"customer_id": FromRequest("customer_id")},
        output=list[str],
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="explicit contract unenforced"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            customer=Required(producer),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": AgentChoice(from_result=producer, item_type=str),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_agent_choice_may_not_offer_a_scalar_result():
    """`str` is validatable, but it is not a collection of selectable items.

    Its items are characters, so offering one as a choice is not a bounded semantic
    selection. This is stricter than the earlier rule, which only required the
    producer to declare some output type.
    """
    producer = Operation(
        scalar_lookup, bind={"customer_id": FromRequest("customer_id")}, output=str
    )
    summon = Summon("svc")

    with pytest.raises(TypeError, match="not a collection of selectable items"):

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            tier=Required(producer),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": AgentChoice(from_result=producer, item_type=str),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...


def test_the_unstructured_output_error_recommends_something_accepted():
    """An error that names a rejected declaration sends the reader in a circle."""
    producer = Operation(
        scalar_lookup, bind={"customer_id": FromRequest("customer_id")}, output=str
    )
    summon = Summon("svc")

    with pytest.raises(TypeError) as error:

        @summon("/orders")
        def create_order(
            request: OrderRequest,
            tier=Required(producer),
            order=Required(
                Operation(
                    place_order,
                    bind={
                        "customer_id": FromRequest("customer_id"),
                        "tier": FromResult(producer, "anything"),
                        "sku": FromRequest("sku"),
                    },
                    output=OrderResponse,
                )
            ),
        ) -> OrderResponse:
            """Place an order."""
            ...

    message = str(error.value)
    assert "Pydantic model" in message
    # A dataclass output is refused, so recommending one would be a dead end.
    assert "dataclass" not in message
