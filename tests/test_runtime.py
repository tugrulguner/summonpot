"""Tests for the provider-agnostic agent runtime."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from summonpot import Pot, Required
from summonpot.runtime import Runtime


class ResearchRequest(BaseModel):
    query: str


class ResearchResponse(BaseModel):
    summary: str
    confidence: float


def _register_endpoint(pot: Pot, *, model: str | None = None) -> None:
    @pot.summon("/research", model=model)
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        raise NotImplementedError


def test_runtime_normalizes_explicit_and_legacy_model_names():
    runtime = Runtime(model="anthropic:claude-sonnet-4-5")

    assert runtime.default_model == "anthropic:claude-sonnet-4-5"
    assert Runtime(model="openrouter:anthropic/claude-sonnet-4").default_model == (
        "openrouter:anthropic/claude-sonnet-4"
    )
    assert Runtime(model="gpt-4o-mini").default_model == "openai:gpt-4o-mini"


def test_endpoint_model_override_wins_without_provider_specific_logic():
    pot = Pot("svc")
    _register_endpoint(pot, model="groq:llama-3.3-70b-versatile")
    runtime = Runtime(model="anthropic:claude-sonnet-4-5")

    assert runtime.model_for(pot.endpoints[0]) == "groq:llama-3.3-70b-versatile"


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

    pot = Pot("svc")
    _register_endpoint(pot)
    runtime = Runtime(model=FunctionModel(model_function))

    result = asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))

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

    pot = Pot("svc")
    _register_endpoint(pot)
    runtime = Runtime(model=FunctionModel(model_function), retries=0)

    with pytest.raises(UnexpectedModelBehavior, match="maximum output retries"):
        asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))


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

    pot = Pot("svc", tools=[search_web])
    _register_endpoint(pot)
    runtime = Runtime(model=FunctionModel(model_function))

    result = asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))

    assert tool_calls == ["agents"]
    assert model_turns == 2
    assert result == ResearchResponse(summary="Grounded result", confidence=1.0)


def test_runtime_rejects_final_output_until_required_capability_runs():
    capability_calls: list[str] = []
    model_turns = 0

    def load_sources(query: str) -> str:
        """Load authoritative sources for the query."""
        capability_calls.append(query)
        return "Required result"

    pot = Pot("svc")

    @pot.summon("/research")
    def research(
        request: ResearchRequest,
        sources=Required(load_sources),
    ) -> ResearchResponse:
        """Research using the declared source capability."""
        raise NotImplementedError

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
    result = asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))

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

    pot = Pot("svc")

    @pot.summon("/research")
    def research(
        request: ResearchRequest,
        sources=Required(load_sources),
    ) -> ResearchResponse:
        raise NotImplementedError

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
        asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))
    assert capability_calls == 0
    assert model_turns == 1


def test_optional_capability_may_be_skipped():
    calls = 0

    def search_web(query: str) -> str:
        nonlocal calls
        calls += 1
        return query

    pot = Pot("svc", tools=[search_web])
    _register_endpoint(pot)

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
            pot.endpoints[0], {"query": "agents"}
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
    pot = Pot("svc")

    @pot.summon("/legacy")
    def legacy(value: str) -> dict:
        return {}

    def model_function(messages, info: AgentInfo):
        return ModelResponse(parts=[TextPart(model_output)])

    result = asyncio.run(
        Runtime(model=FunctionModel(model_function)).call(
            pot.endpoints[0], {"value": "input"}
        )
    )

    assert result == expected
