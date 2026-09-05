"""Tests for the provider-agnostic agent runtime."""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import BaseModel, Field
from pydantic_ai import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from summonpot import (
    AgentChoice,
    Depends,
    Exactly,
    FromRequest,
    Operation,
    Required,
    Summon,
    UsageLimits,
)
from summonpot._execution import _RequestValues
from summonpot.runtime import Runtime, _OperationOutputError


class ResearchRequest(BaseModel):
    query: str


class ResearchResponse(BaseModel):
    summary: str
    confidence: float


class CustomerRecord(BaseModel):
    customer_id: str
    format: str


class NativeCustomerRequest(BaseModel):
    customer_id: UUID = Field(alias="customerId")


class NativeCustomerRecord(BaseModel):
    customer_id: UUID
    format: str


class DirectCustomerResponse(BaseModel):
    customer_id: UUID
    include_history: bool


class TagRequest(BaseModel):
    tags: list[str]


class TagResponse(BaseModel):
    tags: list[str]


def _register_endpoint(summon: Summon, *, model: str | None = None) -> None:
    @summon("/research", model=model)
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        ...


def test_direct_exact_operation_skips_model_resolution():
    customer_id = UUID("12345678-1234-5678-1234-567812345678")
    received: list[tuple[UUID, bool]] = []

    def load_customer(
        requested_id: UUID,
        include_history: bool = False,
        /,
    ) -> DirectCustomerResponse:
        """Load one customer without an agent-owned decision."""
        received.append((requested_id, include_history))
        return DirectCustomerResponse(
            customer_id=requested_id,
            include_history=include_history,
        )

    lookup = Operation(
        load_customer,
        bind={"requested_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/direct")
    def customer(
        request: NativeCustomerRequest,
        result=Required(lookup, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Return the requested customer directly."""
        ...

    runtime = Runtime(model="invalid-provider:no-model")
    result = asyncio.run(
        runtime.call(summon.endpoints[0], {"customerId": str(customer_id)})
    )

    assert result == DirectCustomerResponse(
        customer_id=customer_id,
        include_history=False,
    )
    assert received == [(customer_id, False)]
    assert runtime._agents == {}


def test_direct_operation_failure_never_falls_back_to_a_model():
    starts = 0

    def fail(customer_id: UUID) -> DirectCustomerResponse:
        """Fail after direct execution starts."""
        nonlocal starts
        starts += 1
        raise ValueError("application failure")

    operation = Operation(
        fail,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/fail")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Fail without changing executors."""
        ...

    runtime = Runtime(model="invalid-provider:no-model")
    with pytest.raises(ValueError, match="application failure"):
        asyncio.run(
            runtime.call(
                summon.endpoints[0],
                {"customerId": "12345678-1234-5678-1234-567812345678"},
            )
        )

    assert starts == 1
    assert runtime._agents == {}


def test_direct_operation_invalid_output_is_not_replayed_or_sent_to_a_model():
    starts = 0

    def malformed(customer_id: UUID) -> DirectCustomerResponse:
        """Return an invalid declared output."""
        nonlocal starts
        starts += 1
        return {"customer_id": customer_id}  # type: ignore[return-value]

    operation = Operation(
        malformed,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/malformed")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Validate direct operation output locally."""
        ...

    runtime = Runtime(model="invalid-provider:no-model")
    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            runtime.call(
                summon.endpoints[0],
                {"customerId": "12345678-1234-5678-1234-567812345678"},
            )
        )

    assert starts == 1
    assert runtime._agents == {}


@pytest.mark.parametrize("use_subclass", [False, True])
def test_direct_operation_revalidates_constructed_model_output(use_subclass: bool):
    class UnsafeResponse(DirectCustomerResponse):
        pass

    def malformed(customer_id: UUID) -> DirectCustomerResponse:
        response_type = UnsafeResponse if use_subclass else DirectCustomerResponse
        return response_type.model_construct(
            customer_id="not-a-uuid", include_history=False
        )

    operation = Operation(
        malformed,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/constructed")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Reject an unvalidated model instance from application code."""
        ...

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid-provider:no-model").call(
                summon.endpoints[0],
                {"customerId": "12345678-1234-5678-1234-567812345678"},
            )
        )


def test_direct_request_ignores_untrusted_prevalidated_typed_values():
    requested = UUID("12345678-1234-5678-1234-567812345678")
    forged = UUID("87654321-4321-8765-4321-876543218765")

    def load_customer(customer_id: UUID) -> DirectCustomerResponse:
        return DirectCustomerResponse(
            customer_id=customer_id,
            include_history=False,
        )

    operation = Operation(
        load_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/prevalidated")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Use only the registered request adapter as the trust boundary."""
        ...

    params = _RequestValues(
        {"customerId": str(requested)}, typed={"customer_id": forged}
    )
    result = asyncio.run(
        Runtime(model="invalid-provider:no-model").call(summon.endpoints[0], params)
    )

    assert result.customer_id == requested


def test_direct_request_detaches_nested_values_from_the_caller():
    def extend(tags: list[str]) -> TagResponse:
        tags.append("runtime")
        return TagResponse(tags=tags)

    operation = Operation(
        extend,
        bind={"tags": FromRequest("tags")},
        output=TagResponse,
    )
    summon = Summon("svc")

    @summon("/tags")
    def tags(
        request: TagRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> TagResponse:
        """Keep direct request state isolated from caller-owned containers."""
        ...

    payload = {"tags": ["caller"]}
    result = asyncio.run(
        Runtime(model="invalid-provider:no-model").call(summon.endpoints[0], payload)
    )

    assert result.tags == ["caller", "runtime"]
    assert payload == {"tags": ["caller"]}


def test_direct_operation_uses_registration_time_callable_defaults():
    defaults = ["registered"]

    def extend(tags: list[str], suffixes: list[str] = defaults) -> TagResponse:
        return TagResponse(tags=[*tags, *suffixes])

    operation = Operation(
        extend,
        bind={"tags": FromRequest("tags")},
        output=TagResponse,
    )
    summon = Summon("svc")

    @summon("/tags/default")
    def tags(
        request: TagRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> TagResponse:
        """Use the callable default captured when the endpoint was registered."""
        ...

    defaults.append("mutated")
    result = asyncio.run(
        Runtime(model="invalid-provider:no-model").call(
            summon.endpoints[0], {"tags": ["caller"]}
        )
    )

    assert result.tags == ["caller", "registered"]


def test_default_only_operation_stays_on_the_agent_path():
    def status(include_history: bool = False) -> DirectCustomerResponse:
        return DirectCustomerResponse(
            customer_id=UUID("12345678-1234-5678-1234-567812345678"),
            include_history=include_history,
        )

    operation = Operation(status, bind={}, output=DirectCustomerResponse)
    summon = Summon("svc")

    @summon("/customers/status")
    def customer(
        request: ResearchRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Keep empty-binding operations agent-backed."""
        ...

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("status", {})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "customer_id": "12345678-1234-5678-1234-567812345678",
                        "include_history": False,
                    },
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function))
    asyncio.run(runtime.call(summon.endpoints[0], {"query": "status"}))

    assert turns == 2
    assert len(runtime._agents) == 1


def test_direct_timeout_does_not_retry_or_switch_to_a_model():
    starts = 0

    def slow(customer_id: UUID) -> DirectCustomerResponse:
        """Finish after the request deadline has expired."""
        nonlocal starts
        starts += 1
        time.sleep(0.05)
        return DirectCustomerResponse(
            customer_id=customer_id,
            include_history=False,
        )

    operation = Operation(
        slow,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/slow")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Apply one deadline to direct execution."""
        ...

    runtime = Runtime(model="invalid-provider:no-model", timeout=0.01)
    with pytest.raises(TimeoutError):
        asyncio.run(
            runtime.call(
                summon.endpoints[0],
                {"customerId": "12345678-1234-5678-1234-567812345678"},
            )
        )

    assert starts == 1
    assert runtime._agents == {}


def test_output_composition_keeps_the_agent_path():
    customer_id = UUID("12345678-1234-5678-1234-567812345678")

    def load_customer(customer_id: UUID) -> NativeCustomerRecord:
        """Load a record that does not itself satisfy the endpoint response."""
        return NativeCustomerRecord(customer_id=customer_id, format="summary")

    operation = Operation(
        load_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=NativeCustomerRecord,
    )
    summon = Summon("svc")

    @summon("/customers/composed")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Compose a different endpoint response from the operation result."""
        ...

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            assert info.function_tools[0].parameters_json_schema["properties"] == {}
            return ModelResponse(parts=[ToolCallPart("load_customer", {})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "customer_id": str(customer_id),
                        "include_history": False,
                    },
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function))
    result = asyncio.run(
        runtime.call(summon.endpoints[0], {"customerId": str(customer_id)})
    )

    assert result.customer_id == customer_id
    assert turns == 2
    assert len(runtime._agents) == 1


def test_concurrent_direct_calls_keep_independent_exactly_once_state():
    starts: list[str] = []

    async def load_customer(customer_id: UUID) -> DirectCustomerResponse:
        """Load one customer while another request may be running."""
        starts.append(str(customer_id))
        await asyncio.sleep(0)
        return DirectCustomerResponse(
            customer_id=customer_id,
            include_history=False,
        )

    operation = Operation(
        load_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/concurrent")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Load one customer per request."""
        ...

    identifiers = [
        UUID("12345678-1234-5678-1234-567812345678"),
        UUID("87654321-4321-8765-4321-876543218765"),
    ]
    runtime = Runtime(model="invalid-provider:no-model")

    async def run_both() -> list[DirectCustomerResponse]:
        return await asyncio.gather(
            *(
                runtime.call(
                    summon.endpoints[0],
                    {"customerId": str(identifier)},
                )
                for identifier in identifiers
            )
        )

    results = asyncio.run(run_both())

    assert [result.customer_id for result in results] == identifiers
    assert sorted(starts) == sorted(str(identifier) for identifier in identifiers)
    assert runtime._agents == {}


def test_direct_execution_uses_the_registered_immutable_plan():
    original_calls = 0
    attacker_calls = 0

    def load_customer(customer_id: UUID) -> DirectCustomerResponse:
        """Load the registered customer."""
        nonlocal original_calls
        original_calls += 1
        return DirectCustomerResponse(
            customer_id=customer_id,
            include_history=False,
        )

    def attacker(customer_id: UUID) -> DirectCustomerResponse:
        nonlocal attacker_calls
        attacker_calls += 1
        return DirectCustomerResponse(
            customer_id=customer_id,
            include_history=True,
        )

    operation = Operation(
        load_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/immutable")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Use only the registered direct operation."""
        ...

    endpoint = summon.endpoints[0]
    endpoint.tools[0].fn = attacker
    endpoint.tools.clear()
    endpoint.output_model = NativeCustomerRecord

    result = asyncio.run(
        Runtime(model="invalid-provider:no-model").call(
            endpoint,
            {"customerId": "12345678-1234-5678-1234-567812345678"},
        )
    )

    assert result.include_history is False
    assert original_calls == 1
    assert attacker_calls == 0


def test_unregistered_endpoint_metadata_cannot_activate_direct_execution():
    calls = 0

    def load_customer(customer_id: UUID) -> DirectCustomerResponse:
        """Load one customer through an otherwise direct-eligible operation."""
        nonlocal calls
        calls += 1
        return DirectCustomerResponse(
            customer_id=customer_id,
            include_history=False,
        )

    operation = Operation(
        load_customer,
        bind={"customer_id": FromRequest("customer_id")},
        output=DirectCustomerResponse,
    )
    summon = Summon("svc")

    @summon("/customers/unregistered")
    def customer(
        request: NativeCustomerRequest,
        result=Required(operation, calls=Exactly(1)),
    ) -> DirectCustomerResponse:
        """Keep compatibility metadata on the validated agent path."""
        ...

    endpoint = replace(summon.endpoints[0])
    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("load_customer", {})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "customer_id": "12345678-1234-5678-1234-567812345678",
                        "include_history": False,
                    },
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function))
    result = asyncio.run(
        runtime.call(
            endpoint,
            {"customerId": "12345678-1234-5678-1234-567812345678"},
        )
    )

    assert result.include_history is False
    assert calls == 1
    assert turns == 2
    assert len(runtime._agents) == 1


def test_bound_operation_hides_and_injects_request_arguments():
    received: list[tuple[str, str, bool]] = []

    def load_customer(
        customer_id: str,
        format: str,
        include_history: bool = False,
    ) -> CustomerRecord:
        """Load one customer in the selected format."""
        received.append((customer_id, format, include_history))
        return CustomerRecord(customer_id=customer_id, format=format)

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("query"),
            "format": AgentChoice(),
        },
        output=CustomerRecord,
    )
    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        customer=Required(lookup, calls=Exactly(1)),
    ) -> ResearchResponse:
        """Research using the requested customer."""
        ...

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            schema = info.function_tools[0].parameters_json_schema
            assert sorted(schema["properties"]) == ["format"]
            return ModelResponse(
                parts=[ToolCallPart("load_customer", {"format": "summary"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "customer-7", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "customer-7"}
        )
    )

    assert received == [("customer-7", "summary", False)]
    assert result == ResearchResponse(summary="customer-7", confidence=1.0)


def test_runtime_validates_and_snapshots_aliased_request_values():
    customer_id = UUID("12345678-1234-5678-1234-567812345678")
    received: list[UUID] = []

    def load_customer(customer_id: UUID, format: str) -> NativeCustomerRecord:
        """Load one customer from a canonical typed identifier."""
        received.append(customer_id)
        return NativeCustomerRecord(customer_id=customer_id, format=format)

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("customer_id"),
            "format": AgentChoice(),
        },
        output=NativeCustomerRecord,
    )
    summon = Summon("svc")

    @summon("/customers")
    def customer(
        request: NativeCustomerRequest,
        record=Required(lookup, calls=Exactly(1)),
    ) -> ResearchResponse:
        """Load the aliased customer and return a response."""
        ...

    raw = {"customerId": str(customer_id)}
    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            raw["customerId"] = "00000000-0000-0000-0000-000000000000"
            assert sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            ) == ["format"]
            return ModelResponse(
                parts=[ToolCallPart("load_customer", {"format": "summary"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "typed", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(summon.endpoints[0], raw)
    )

    assert result.summary == "typed"
    assert received == [customer_id]


def test_bound_operation_preserves_hidden_positional_only_defaults():
    received: list[tuple[str, bool, str]] = []

    def load_customer(
        customer_id: str,
        include_history: bool = False,
        format: str = "summary",
        /,
    ) -> CustomerRecord:
        """Load one customer while preserving application defaults."""
        received.append((customer_id, include_history, format))
        return CustomerRecord(customer_id=customer_id, format=format)

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("query"),
            "format": AgentChoice(),
        },
        output=CustomerRecord,
    )
    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        customer=Required(lookup, calls=Exactly(1)),
    ) -> ResearchResponse:
        """Research using one customer lookup."""
        ...

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            assert sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            ) == ["format"]
            return ModelResponse(
                parts=[ToolCallPart("load_customer", {"format": "detailed"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "customer-7", "confidence": 1.0},
                )
            ]
        )

    asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "customer-7"}
        )
    )

    assert received == [("customer-7", False, "detailed")]


def test_exactly_once_rejects_a_second_start_before_application_code():
    starts = 0

    def load_customer(customer_id: str, format: str) -> CustomerRecord:
        """Load one customer in the selected format."""
        nonlocal starts
        starts += 1
        return CustomerRecord(customer_id=customer_id, format=format)

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("query"),
            "format": AgentChoice(),
        },
        output=CustomerRecord,
    )
    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        customer=Required(lookup, calls=Exactly(1)),
    ) -> ResearchResponse:
        """Research using exactly one customer lookup."""
        ...

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart("load_customer", {"format": "summary"}),
                    ToolCallPart("load_customer", {"format": "detailed"}),
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "one lookup", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "customer-7"}
        )
    )

    assert starts == 1
    assert result.summary == "one lookup"


def test_invalid_operation_output_fails_without_retrying_the_operation():
    starts = 0

    def load_customer(customer_id: str, format: str) -> CustomerRecord:
        """Return a malformed customer record."""
        nonlocal starts
        starts += 1
        return {"customer_id": customer_id}  # type: ignore[return-value]

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("query"),
            "format": AgentChoice(),
        },
        output=CustomerRecord,
    )
    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        customer=Required(lookup, calls=Exactly(1)),
    ) -> ResearchResponse:
        """Research with one validated customer lookup."""
        ...

    def model_function(messages, info: AgentInfo):
        return ModelResponse(
            parts=[ToolCallPart("load_customer", {"format": "summary"})]
        )

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model=FunctionModel(model_function), retries=3).call(
                summon.endpoints[0], {"query": "customer-7"}
            )
        )

    assert starts == 1


def test_post_registration_metadata_mutation_cannot_change_execution():
    original_calls = 0
    attacker_calls = 0

    def load_customer(customer_id: str, format: str) -> CustomerRecord:
        """Load the registered customer operation."""
        nonlocal original_calls
        original_calls += 1
        return CustomerRecord(customer_id=customer_id, format=format)

    def attacker(customer_id: str, format: str) -> CustomerRecord:
        nonlocal attacker_calls
        attacker_calls += 1
        return CustomerRecord(customer_id="attacker", format=format)

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("query"),
            "format": AgentChoice(),
        },
        output=CustomerRecord,
    )
    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        customer=Required(lookup, calls=Exactly(1)),
    ) -> ResearchResponse:
        """Research using the registered operation."""
        ...

    endpoint = summon.endpoints[0]
    endpoint.tools[0].fn = attacker
    endpoint.tools[0].name = "attacker"
    endpoint.tools[0].parameters.clear()
    endpoint._execution_plan = None

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            assert [tool.name for tool in info.function_tools] == ["load_customer"]
            assert sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            ) == ["format"]
            return ModelResponse(
                parts=[ToolCallPart("load_customer", {"format": "summary"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "trusted", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            endpoint, {"query": "customer-7"}
        )
    )

    assert result.summary == "trusted"
    assert original_calls == 1
    assert attacker_calls == 0


def test_unsupported_broader_call_bound_keeps_legacy_required_once_behavior():
    starts = 0

    def load_customer(customer_id: str, format: str) -> CustomerRecord:
        """Load one customer in the selected format."""
        nonlocal starts
        starts += 1
        return CustomerRecord(customer_id=customer_id, format=format)

    lookup = Operation(
        load_customer,
        bind={
            "customer_id": FromRequest("query"),
            "format": AgentChoice(),
        },
        output=CustomerRecord,
    )
    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        customer=Required(lookup, calls=Exactly(2)),
    ) -> ResearchResponse:
        """Use the legacy model-supplied path for unsupported broader bounds."""
        ...

    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            assert sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            ) == [
                "customer_id",
                "format",
            ]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "load_customer",
                        {"customer_id": "customer-7", "format": "summary"},
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "legacy", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "customer-7"}
        )
    )

    assert result.summary == "legacy"
    assert starts == 1


def test_runtime_normalizes_explicit_and_legacy_model_names():
    runtime = Runtime(model="anthropic:claude-sonnet-4-5")

    assert runtime.default_model == "anthropic:claude-sonnet-4-5"
    assert Runtime(model="openrouter:anthropic/claude-sonnet-4").default_model == (
        "openrouter:anthropic/claude-sonnet-4"
    )
    assert Runtime(model="gpt-4o-mini").default_model == "openai:gpt-4o-mini"


def test_endpoint_model_override_wins_without_provider_specific_logic():
    summon = Summon("svc")
    _register_endpoint(summon, model="groq:llama-3.3-70b-versatile")
    runtime = Runtime(model="anthropic:claude-sonnet-4-5")

    assert runtime.model_for(summon.endpoints[0]) == "groq:llama-3.3-70b-versatile"


def test_runtime_returns_declared_model_with_provider_neutral_engine():
    def model_function(messages, info: AgentInfo):
        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "summary": "Provider-neutral contracts",
                        "confidence": 0.95,
                    },
                )
            ]
        )

    summon = Summon("svc")
    _register_endpoint(summon)
    runtime = Runtime(model=FunctionModel(model_function))

    result = asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))

    assert result == ResearchResponse(
        summary="Provider-neutral contracts",
        confidence=0.95,
    )


def test_runtime_rejects_output_that_violates_response_model():
    def model_function(messages, info: AgentInfo):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "Incomplete"},
                )
            ]
        )

    summon = Summon("svc")
    _register_endpoint(summon)
    runtime = Runtime(model=FunctionModel(model_function), retries=0)

    with pytest.raises(UnexpectedModelBehavior, match="maximum output retries"):
        asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))


def test_runtime_executes_tools_through_provider_neutral_agent_loop():
    tool_calls: list[str] = []
    model_turns = 0

    def search_web(query: str) -> str:
        """Search the web for a topic."""
        tool_calls.append(query)
        return "Grounded result"

    def model_function(messages, info: AgentInfo):
        nonlocal model_turns
        model_turns += 1
        if model_turns == 1:
            assert info.function_tools[0].name == "search_web"
            return ModelResponse(
                parts=[ToolCallPart("search_web", {"query": "agents"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "Grounded result", "confidence": 1.0},
                )
            ]
        )

    summon = Summon("svc", tools=[search_web])
    _register_endpoint(summon)
    runtime = Runtime(model=FunctionModel(model_function))

    result = asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))

    assert tool_calls == ["agents"]
    assert model_turns == 2
    assert result == ResearchResponse(summary="Grounded result", confidence=1.0)


def test_declared_parameters_match_the_schema_the_model_receives():
    """ToolDef.parameters is the documented contract; the schema must agree."""

    def archive_record(identifier: str, force: bool = False) -> str:
        """Archive one approved record."""
        return identifier

    summon = Summon("svc", tools=[archive_record])
    _register_endpoint(summon)
    observed: dict[str, object] = {}

    def model_function(messages, info: AgentInfo):
        schema = info.function_tools[0].parameters_json_schema
        observed["properties"] = sorted(schema["properties"])
        observed["required"] = sorted(schema.get("required", []))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "done", "confidence": 1.0},
                )
            ]
        )

    asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "agents"}
        )
    )

    declared = summon.endpoints[0].tools[0].parameters
    assert observed["properties"] == sorted(p.name for p in declared)
    assert observed["required"] == sorted(p.name for p in declared if p.required)


@pytest.mark.parametrize("capability_kind", ["partial", "callable_object"])
def test_runtime_exposes_capabilities_that_are_not_plain_functions(capability_kind):
    """Partials and callable instances are how a capability carries state."""

    def fetch_record(table: str, identifier: str) -> str:
        """Fetch one approved record."""
        return f"{table}:{identifier}"

    class LookupAccount:
        """Look up an account through a framework-owned connection."""

        def __init__(self, connection: str) -> None:
            self.connection = connection

        def __call__(self, identifier: str) -> str:
            return f"{self.connection}:{identifier}"

    if capability_kind == "partial":
        capability = functools.partial(fetch_record, "accounts")
        expected_name = "fetch_record"
    else:
        capability = LookupAccount("accounts")
        expected_name = "LookupAccount"

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest, record=Depends(capability)
    ) -> ResearchResponse:
        """Research using a stateful capability."""
        ...

    observed: dict[str, object] = {}
    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            observed["name"] = info.function_tools[0].name
            observed["properties"] = sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            )
            return ModelResponse(
                parts=[ToolCallPart(expected_name, {"identifier": "7"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "accounts:7", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "agents"}
        )
    )

    assert observed["name"] == expected_name
    # The bound argument must not be offered back to the model.
    assert observed["properties"] == ["identifier"]
    assert result.summary == "accounts:7"


def test_runtime_rejects_final_output_until_required_capability_runs():
    capability_calls: list[str] = []
    model_turns = 0

    def load_sources(query: str) -> str:
        """Load authoritative sources for the query."""
        capability_calls.append(query)
        return "Required result"

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        sources=Required(load_sources),
    ) -> ResearchResponse:
        """Research using the declared source capability."""
        ...

    def model_function(messages, info: AgentInfo):
        nonlocal model_turns
        model_turns += 1
        if model_turns == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"summary": "Unsupported", "confidence": 0.1},
                    )
                ]
            )
        if model_turns == 2:
            return ModelResponse(
                parts=[ToolCallPart("load_sources", {"query": "agents"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "Required result", "confidence": 1.0},
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function), retries=2)
    result = asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))

    assert capability_calls == ["agents"]
    assert model_turns == 3
    assert result == ResearchResponse(summary="Required result", confidence=1.0)


def test_runtime_fails_when_required_capability_never_runs():
    capability_calls = 0
    model_turns = 0

    def load_sources(query: str) -> str:
        nonlocal capability_calls
        capability_calls += 1
        return query

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        sources=Required(load_sources),
    ) -> ResearchResponse:
        """Research a topic."""
        ...

    def model_function(messages, info: AgentInfo):
        nonlocal model_turns
        model_turns += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "Skipped", "confidence": 0.0},
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function), retries=0)

    with pytest.raises(UnexpectedModelBehavior, match="maximum output retries"):
        asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))
    assert capability_calls == 0
    assert model_turns == 1


def test_optional_capability_may_be_skipped():
    calls = 0

    def search_web(query: str) -> str:
        nonlocal calls
        calls += 1
        return query

    summon = Summon("svc", tools=[search_web])
    _register_endpoint(summon)

    def model_function(messages, info: AgentInfo):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "No lookup needed", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "agents"}
        )
    )

    assert calls == 0
    assert result.summary == "No lookup needed"


@pytest.mark.parametrize(
    ("model_output", "expected"),
    [
        ('{"status": "ready"}', {"status": "ready"}),
        ("not-json", "not-json"),
    ],
)
def test_legacy_structured_return_parses_json_when_possible(model_output, expected):
    summon = Summon("svc")

    @summon("/legacy")
    def legacy(value: str) -> dict:
        """Return a legacy structured payload."""
        return {}

    def model_function(messages, info: AgentInfo):
        return ModelResponse(parts=[TextPart(model_output)])

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"value": "input"}
        )
    )

    assert result == expected


@pytest.mark.parametrize(
    ("capability_kind", "expected_name"),
    [
        ("async_callable", "AsyncLookup"),
        ("positional_only_function", "lookup_positionally"),
        ("positional_only_callable", "PositionalLookup"),
    ],
)
def test_runtime_supports_every_callable_capability_form(
    capability_kind, expected_name
):
    """Each form must reach the model with the right schema and actually run."""

    class AsyncLookup:
        """Look up an account asynchronously."""

        async def __call__(self, identifier: str) -> str:
            return f"async:{identifier}"

    def lookup_positionally(identifier: str, /) -> str:
        """Look up an account positionally."""
        return f"positional:{identifier}"

    class PositionalLookup:
        """Look up an account positionally."""

        def __call__(self, identifier: str, /) -> str:
            return f"object:{identifier}"

    capability = {
        "async_callable": AsyncLookup(),
        "positional_only_function": lookup_positionally,
        "positional_only_callable": PositionalLookup(),
    }[capability_kind]

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest, record=Depends(capability)
    ) -> ResearchResponse:
        """Research a topic."""
        ...

    observed: dict[str, object] = {}
    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            observed["name"] = info.function_tools[0].name
            observed["properties"] = sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            )
            return ModelResponse(
                parts=[ToolCallPart(expected_name, {"identifier": "7"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "done", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "agents"}
        )
    )

    assert observed["name"] == expected_name
    # A positional-only parameter is still offered to the model by name.
    assert observed["properties"] == ["identifier"]
    assert result.summary == "done"


def test_default_model_is_resolved_lazily(monkeypatch):
    """Setting SUMMONPOT_MODEL after the application is built must still take effect."""
    monkeypatch.delenv("SUMMONPOT_MODEL", raising=False)
    runtime = Runtime()

    assert runtime.default_model == "openai:gpt-4o-mini"

    monkeypatch.setenv("SUMMONPOT_MODEL", "anthropic:claude-sonnet-4-5")

    assert runtime.default_model == "anthropic:claude-sonnet-4-5"


def test_explicit_model_beats_the_environment(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "anthropic:claude-sonnet-4-5")

    assert Runtime(model="groq:llama-3.3-70b-versatile").default_model == (
        "groq:llama-3.3-70b-versatile"
    )


def test_usage_limits_bound_a_runaway_agent_loop():
    """An endpoint is an operator-funded call; it must be cappable."""
    calls = 0

    def search_web(query: str) -> str:
        """Search the web."""
        nonlocal calls
        calls += 1
        return "result"

    summon = Summon("svc", tools=[search_web])
    _register_endpoint(summon)

    def model_function(messages, info: AgentInfo):
        # Never finishes on its own.
        return ModelResponse(parts=[ToolCallPart("search_web", {"query": "agents"})])

    runtime = Runtime(
        model=FunctionModel(model_function),
        usage_limits=UsageLimits(request_limit=2),
    )

    with pytest.raises(UsageLimitExceeded):
        asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))
    assert calls <= 2


def test_timeout_bounds_a_single_endpoint_call():
    async def slow_model(messages, info: AgentInfo):
        await asyncio.sleep(5)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "late", "confidence": 1.0},
                )
            ]
        )

    summon = Summon("svc")
    _register_endpoint(summon)
    runtime = Runtime(model=FunctionModel(slow_model), timeout=0.05)

    with pytest.raises(TimeoutError):
        asyncio.run(runtime.call(summon.endpoints[0], {"query": "agents"}))


def test_runtime_is_unbounded_by_default():
    runtime = Runtime(model="openai:gpt-4o-mini")

    assert runtime.usage_limits is None
    assert runtime.timeout is None


def test_timeout_bounds_a_slow_synchronous_capability():
    """The deadline must apply to sync capabilities, which run in a worker thread."""
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_write(query: str) -> str:
        """Perform a slow synchronous write."""
        entered.set()
        release.wait(timeout=2.0)
        finished.set()
        return "written"

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest, sources=Required(slow_write)
    ) -> ResearchResponse:
        """Research a topic."""
        ...

    def model_function(messages, info: AgentInfo):
        return ModelResponse(parts=[ToolCallPart("slow_write", {"query": "a"})])

    # Give CI enough time to schedule both the synchronous model and capability
    # workers. Once the capability enters application code, it blocks until the
    # request deadline has definitely expired.
    runtime = Runtime(model=FunctionModel(model_function), timeout=0.50)

    async def scenario() -> float:
        # Measured inside the loop: this is what one request waits. Measuring around
        # asyncio.run would instead time the loop teardown, which joins the
        # abandoned worker thread.
        started = time.perf_counter()
        try:
            with pytest.raises(TimeoutError):
                await runtime.call(summon.endpoints[0], {"query": "agents"})
            return time.perf_counter() - started
        finally:
            release.set()

    elapsed = asyncio.run(scenario())

    assert entered.is_set(), "the capability did not start before the request deadline"
    # The caller is released on the deadline, not when the capability finishes.
    assert elapsed < 1.25, f"the request waited {elapsed:.3f}s for the capability"

    # Documented boundary: the thread is not killed, so the side effect still lands
    # after the caller has already seen TimeoutError.
    assert finished.is_set() or finished.wait(timeout=2.0)


def test_agent_is_built_once_per_endpoint():
    summon = Summon("svc")
    _register_endpoint(summon)

    def model_function(messages, info: AgentInfo):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "done", "confidence": 1.0},
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function))
    endpoint = summon.endpoints[0]

    asyncio.run(runtime.call(endpoint, {"query": "a"}))
    first = runtime._agent_for(endpoint)
    asyncio.run(runtime.call(endpoint, {"query": "b"}))

    assert runtime._agent_for(endpoint) is first


def test_required_capability_state_does_not_leak_between_calls():
    """The agent is now shared, so run state must not be."""
    turns = 0

    def load_sources(query: str) -> str:
        """Load sources."""
        return "loaded"

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest, sources=Required(load_sources)
    ) -> ResearchResponse:
        """Research a topic."""
        ...

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        # Call the required capability only on the very first run.
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("load_sources", {"query": "a"})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "done", "confidence": 1.0},
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function), retries=0)
    endpoint = summon.endpoints[0]

    assert asyncio.run(runtime.call(endpoint, {"query": "a"})).summary == "done"

    # A second call must not inherit the first call's completed capability.
    with pytest.raises(UnexpectedModelBehavior, match="maximum output retries"):
        asyncio.run(runtime.call(endpoint, {"query": "b"}))


def test_concurrent_calls_track_required_capabilities_independently():
    def load_sources(query: str) -> str:
        """Load sources."""
        return "loaded"

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest, sources=Required(load_sources)
    ) -> ResearchResponse:
        """Research a topic."""
        ...

    async def model_function(messages, info: AgentInfo):
        called = any(
            part.part_kind == "tool-return" for m in messages for part in m.parts
        )
        if not called:
            await asyncio.sleep(0)
            return ModelResponse(parts=[ToolCallPart("load_sources", {"query": "a"})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "done", "confidence": 1.0},
                )
            ]
        )

    runtime = Runtime(model=FunctionModel(model_function))
    endpoint = summon.endpoints[0]

    async def run_all():
        return await asyncio.gather(
            *(runtime.call(endpoint, {"query": str(n)}) for n in range(4))
        )

    assert [r.summary for r in asyncio.run(run_all())] == ["done"] * 4


def test_capability_may_declare_a_business_field_named_ctx():
    """The injected run context must not collide with a real capability field."""

    def inspect_context(ctx: str) -> str:
        """Inspect an application context value."""
        return f"seen:{ctx}"

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest, dep=Depends(inspect_context)
    ) -> ResearchResponse:
        """Research a topic."""
        ...

    observed: dict[str, object] = {}
    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            observed["properties"] = sorted(
                info.function_tools[0].parameters_json_schema["properties"]
            )
            return ModelResponse(
                parts=[ToolCallPart("inspect_context", {"ctx": "production"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "done", "confidence": 1.0},
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            summon.endpoints[0], {"query": "agents"}
        )
    )

    # The business field survives; the run context is not exposed to the model.
    assert observed["properties"] == ["ctx"]
    assert result.summary == "done"


def test_keyless_test_model_is_not_given_a_provider_prefix():
    """`test` needs no provider; prefixing it demands credentials it never uses."""
    assert Runtime(model="test").default_model == "test"


def test_keyless_test_model_works_through_the_environment(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")

    assert Runtime().default_model == "test"


def test_legacy_openai_names_are_still_prefixed():
    assert Runtime(model="gpt-4o-mini").default_model == "openai:gpt-4o-mini"


def test_endpoint_runs_on_the_keyless_test_model():
    """The end-to-end path a new user takes before they have an API key."""
    summon = Summon("svc", model="test")
    _register_endpoint(summon)

    result = asyncio.run(summon._runtime.call(summon.endpoints[0], {"query": "agents"}))

    assert isinstance(result, ResearchResponse)
