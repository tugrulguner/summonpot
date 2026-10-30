"""Budget, isolation and compatibility invariants of decision-only progression."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage, UsageLimits
from test_decision_progression import progression_app
from test_decision_progression_contract import evidence

from summonpot.runtime import Runtime
from summonpot.server import build_app


def selector(callback=None):
    def model(messages, info):
        assert info.function_tools == []
        domains = evidence(messages)
        if callback is not None:
            callback(messages, info, domains)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        slot: data["candidates"][0]["token"]
                        for slot, data in domains.items()
                    },
                )
            ],
            usage=RequestUsage(input_tokens=5, output_tokens=3),
        )

    return FunctionModel(model)


@pytest.mark.parametrize("limit", [1, 2])
def test_shared_request_limit_spans_two_actual_decisions(limit):
    events, seen = [], []
    endpoint = progression_app(events).endpoints[0]

    def observe(messages, info, domains):
        seen.append(domains)

    runtime = Runtime(
        model=selector(observe), usage_limits=UsageLimits(request_limit=limit)
    )
    if limit == 1:
        with pytest.raises(UsageLimitExceeded):
            asyncio.run(runtime.call(endpoint, {"query": "q"}))
        assert [e[0] for e in events] == ["discover", "middle"]
    else:
        assert asyncio.run(runtime.call(endpoint, {"query": "q"})).value == "a/middle"
        assert [e[0] for e in events] == ["discover", "middle", "finish"]
    assert len(seen) == limit


def test_total_tokens_are_not_reset_at_the_next_frontier():
    events, callbacks = [], []
    app = progression_app(events)

    def record(messages, info, domains):
        callbacks.append(domains)

    runtime = Runtime(
        model=selector(record), usage_limits=UsageLimits(total_tokens_limit=10)
    )
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(runtime.call(app.endpoints[0], {"query": "q"}))
    assert len(callbacks) == 2
    assert [e[0] for e in events] == ["discover", "middle"]


def test_default_limits_usage_and_model_resolution_are_shared(monkeypatch):
    events, captures, resolutions = [], [], []
    app = progression_app(events)
    original = Runtime._select_choices
    original_model = Runtime.model_for

    async def capture(self, plan, tool, ambiguous, request, model, usage, limits):
        captures.append((usage, limits, usage.requests))
        return await original(
            self, plan, tool, ambiguous, request, model, usage, limits
        )

    def resolve(self, endpoint):
        resolutions.append(endpoint)
        return original_model(self, endpoint)

    def forbidden(*args, **kwargs):
        raise AssertionError("progression must not enter the full endpoint agent")

    monkeypatch.setattr(Runtime, "_select_choices", capture)
    monkeypatch.setattr(Runtime, "model_for", resolve)
    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    result = asyncio.run(
        Runtime(model=selector()).call(app.endpoints[0], {"query": "q"})
    )
    assert result.value == "a/middle"
    assert len(resolutions) == 1 and len(captures) == 2
    assert captures[0][0] is captures[1][0]
    assert captures[0][1] is captures[1][1]
    assert captures[0][1].request_limit == UsageLimits().request_limit
    assert [v[2] for v in captures] == [0, 1]
    assert captures[1][0].requests == 2


def test_explicit_zero_tool_quota_remains_enforced_by_compatibility_route():
    events, callbacks = [], []
    app = progression_app(events)

    def old_model(messages, info):
        callbacks.append([t.name for t in info.function_tools])
        tool = info.function_tools[0]
        fields = tool.parameters_json_schema["properties"]
        return ModelResponse(
            parts=[
                ToolCallPart(tool.name, {k: v["enum"][0] for k, v in fields.items()})
            ]
        )

    app._runtime = Runtime(
        model=FunctionModel(old_model), usage_limits=UsageLimits(tool_calls_limit=0)
    )
    with TestClient(build_app(app)) as client:
        response = client.post("/progress", json={"query": "q"})
    assert response.status_code == 429
    assert events == [("discover", "q")]
    assert callbacks == [["middle"]]


def test_selector_transcripts_and_tokens_are_request_and_frontier_local():
    events, transcripts, token_sets = [], [], []
    app = progression_app(events)

    def record(messages, info, domains):
        transcripts.append(repr(messages))
        token_sets.append(
            {c["token"] for data in domains.values() for c in data["candidates"]}
        )

    runtime = Runtime(model=selector(record))

    async def run_all():
        return await asyncio.gather(
            *(runtime.call(app.endpoints[0], {"query": f"q{i}"}) for i in range(4))
        )

    results = asyncio.run(run_all())
    assert all(r.value == "a/middle" for r in results)
    assert len(token_sets) == 8
    assert sum(len(s) for s in token_sets) == len(set.union(*token_sets))
    for i, text in enumerate(transcripts):
        assert all(
            not any(token in text for token in tokens)
            for j, tokens in enumerate(token_sets)
            if j != i
        )
    assert [e[0] for e in events].count("finish") == 4


def test_ambiguous_singleton_ambiguous_progresses_locally_between_decisions():
    from test_multiple_choice_adversarial import staged_chain

    events = []
    app = staged_chain((2, 1, 2), events)

    def record(messages, info, domains):
        events.append("decision")

    result = asyncio.run(
        Runtime(model=selector(record)).call(app.endpoints[0], {"query": "q"})
    )
    assert result.key == "q-0-0-0"
    assert events == ["find", "decision", "step1", "step2", "decision", "finish"]


def test_all_singleton_request_bypasses_selectors_after_prior_ambiguity(monkeypatch):
    from test_multiple_choice_adversarial import staged_chain

    events = []
    counts = [1, 2]
    app = staged_chain(counts, events)
    runtime = Runtime(model=selector())
    assert (
        asyncio.run(runtime.call(app.endpoints[0], {"query": "warm"})).key == "warm-0-0"
    )
    counts[1] = 1

    def forbidden(*args, **kwargs):
        raise AssertionError("all-singleton progression must bypass model and selector")

    for name in ("model_for", "_select_choices", "_agent_for", "_build_agent"):
        monkeypatch.setattr(Runtime, name, forbidden)
    assert (
        asyncio.run(runtime.call(app.endpoints[0], {"query": "local"})).key
        == "local-0-0"
    )


@pytest.mark.parametrize("timeout", [0.01])
def test_deadline_during_selector_prevents_current_consumer(timeout):
    events = []
    app = progression_app(events)

    async def slow(messages, info):
        assert not info.function_tools
        await asyncio.sleep(0.1)
        raise AssertionError("cancelled selector must not complete")

    runtime = Runtime(model=FunctionModel(slow), timeout=timeout)
    with pytest.raises(TimeoutError):
        asyncio.run(runtime.call(app.endpoints[0], {"query": "q"}))
    assert events == [("discover", "q")]
