"""Framework-owned decision progression across producer-backed frontiers."""

import asyncio

import pytest
from pydantic import BaseModel
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import _register_endpoint
from summonpot.runtime import Runtime


class Request(BaseModel):
    query: str


class Candidate(BaseModel):
    value: str


class Result(BaseModel):
    value: str


def progression_app(events: list[tuple], *, singleton_middle: bool = True):
    def discover(query: str) -> list[Candidate]:
        events.append(("discover", query))
        return [Candidate(value="a"), Candidate(value="b")]

    found = Operation(
        discover, bind={"query": FromRequest("query")}, output=list[Candidate]
    )

    def middle(candidate: Candidate) -> list[Candidate]:
        events.append(("middle", candidate.value))
        return (
            [Candidate(value="middle")]
            if singleton_middle
            else [Candidate(value="m1"), Candidate(value="m2")]
        )

    options = Operation(
        middle,
        bind={"candidate": AgentChoice(from_result=found)},
        output=list[Candidate],
    )

    def finish(first: Candidate, second: Candidate) -> Result:
        events.append(("finish", first.value, second.value))
        return Result(value=f"{first.value}/{second.value}")

    terminal = Operation(
        finish,
        bind={
            "first": AgentChoice(from_result=found),
            "second": AgentChoice(from_result=options),
        },
        output=Result,
    )
    app = Summon("decision-progression")

    @app("/progress")
    def endpoint(
        request: Request,
        found=Required(found, calls=Exactly(1)),
        options=Required(options, calls=Exactly(1)),
        result=Required(terminal, calls=Exactly(1)),
    ) -> Result:
        """Choose candidates and complete the declared task."""
        ...

    return app


def test_ambiguous_singleton_ambiguous_uses_decision_only_then_returns_terminal():
    events: list[tuple] = []
    endpoint = progression_app(events).endpoints[0]
    assert _register_endpoint(endpoint).result_dependent_order == (0, 1, 2)
    calls: list[tuple[list[str], dict]] = []

    def model(messages, info):
        assert info.function_tools == [], (
            "decision selectors must expose no business tools"
        )
        assert len(info.output_tools) == 1
        schema = info.output_tools[0].parameters_json_schema
        props = schema["properties"]
        import re

        tokens = re.findall(r'"token": "([A-Za-z0-9_-]+)"', str(messages[0]))
        assert tokens
        args = {name: tokens[0] for name in props}
        calls.append(([tool.name for tool in info.function_tools], args))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(endpoint, {"query": "q"})
    )
    assert result == Result(value="a/middle")
    assert len(calls) == 2
    assert events[0] == ("discover", "q")
    assert events[1][0] == "middle"
    assert events[2][0] == "finish"
    assert sum(event[0] == "finish" for event in events) == 1
    assert all(not function_tools for function_tools, _ in calls)


def test_shared_budget_and_forged_correction_stop_before_later_effect():
    events: list[tuple] = []
    endpoint = progression_app(events).endpoints[0]
    attempts = 0

    def model(messages, info):
        nonlocal attempts
        assert info.function_tools == []
        attempts += 1
        name = info.output_tools[0].name
        field = next(iter(info.output_tools[0].parameters_json_schema["properties"]))
        import re

        tokens = re.findall(r'"token": "([A-Za-z0-9_-]+)"', str(messages[0]))
        assert tokens
        token = "forged" if attempts == 1 else tokens[0]
        return ModelResponse(parts=[ToolCallPart(name, {field: token})])

    runtime = Runtime(model=FunctionModel(model), retries=1)
    runtime.usage_limits = UsageLimits(request_limit=2)
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(runtime.call(endpoint, {"query": "q"}))
    assert attempts == 2
    assert [event[0] for event in events] == ["discover", "middle"]


def test_explicit_tool_calls_limit_keeps_legacy_agent_path():
    from pydantic_ai.usage import UsageLimits

    events: list[tuple] = []
    endpoint = progression_app(events).endpoints[0]
    rounds = 0

    def model(messages, info):
        nonlocal rounds
        rounds += 1
        if info.function_tools:
            tool = info.function_tools[0]
            args = {
                name: field["enum"][0]
                for name, field in tool.parameters_json_schema["properties"].items()
                if "enum" in field
            }
            return ModelResponse(parts=[ToolCallPart(tool.name, args)])
        return ModelResponse(
            parts=[
                __import__("pydantic_ai.messages", fromlist=["TextPart"]).TextPart(
                    "done"
                )
            ]
        )

    result = asyncio.run(
        Runtime(
            model=FunctionModel(model), usage_limits=UsageLimits(tool_calls_limit=3)
        ).call(endpoint, {"query": "q"})
    )
    assert result == Result(value="a/middle")
    assert any(event[0] == "finish" for event in events)
    assert rounds >= 1
