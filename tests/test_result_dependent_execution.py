"""Result-dependent paths use a model only for a remaining candidate choice."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_producer_choice_runtime import Candidate, Receipt, Request, choice_app

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot._execution import _register_endpoint
from summonpot.runtime import Runtime, _ChoiceUnavailableError
from summonpot.server import build_app


@pytest.fixture(autouse=True)
def _historical_agent_tool_compatibility(monkeypatch):
    """Keep these pre-progression historical agent-flow tests on the explicit legacy route."""
    from pydantic_ai.usage import UsageLimits

    original_init = Runtime.__init__

    def init_with_legacy_tool_budget(self, *args, **kwargs):
        if kwargs.get("usage_limits") is None:
            kwargs["usage_limits"] = UsageLimits(tool_calls_limit=100)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(Runtime, "__init__", init_with_legacy_tool_budget)


def test_singleton_chain_never_resolves_or_constructs_a_model(monkeypatch):
    events = []
    app, _ = choice_app(events, candidates=[Candidate(identifier="A", label="only")])

    def forbidden(*args, **kwargs):
        raise AssertionError("singleton path must not resolve or construct a model")

    for name in ("model_for", "_agent_for", "_build_agent"):
        monkeypatch.setattr(Runtime, name, forbidden)
    result = asyncio.run(Runtime().call(app.endpoints[0], {"query": "one"}))
    assert result == Receipt(identifier="A")
    assert [event[0] for event in events] == ["find", "reserve"]


@pytest.mark.parametrize(
    "domain",
    [
        [],
        [Candidate(identifier="huge", label="x" * 65536)],
        [Candidate(identifier=str(i), label="x") for i in range(129)],
    ],
)
def test_unavailable_domains_reject_before_model_or_consumer(monkeypatch, domain):
    events = []
    app, _ = choice_app(events, candidates=domain)

    def forbidden(*args, **kwargs):
        raise AssertionError("unavailable domain must not resolve a model")

    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    with pytest.raises(_ChoiceUnavailableError):
        asyncio.run(Runtime().call(app.endpoints[0], {"query": "none"}))
    assert events == [("find", "none")]


def test_multi_candidate_resolves_after_prefix_and_never_replays_it(monkeypatch):
    events = []
    app, _ = choice_app(events)
    advertised = []
    original = Runtime.model_for

    def model_for(runtime, endpoint):
        assert events == [("find", "two")]
        return original(runtime, endpoint)

    monkeypatch.setattr(Runtime, "model_for", model_for)

    def model(messages, info):
        names = [tool.name for tool in info.function_tools]
        advertised.append(names)
        if names:
            assert names == ["reserve"]
            token = info.function_tools[0].parameters_json_schema["properties"]["item"][
                "enum"
            ][1]
            return ModelResponse(parts=[ToolCallPart("reserve", {"item": token})])
        return ModelResponse(parts=[TextPart("not the authoritative receipt")])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"query": "two"})
    )
    assert result.identifier == "B"
    assert advertised == [["reserve"], []]
    assert [event[0] for event in events] == ["find", "reserve"]


@pytest.mark.parametrize("count,status", [(0, 409), (1, 200)])
def test_http_zero_and_singleton_use_no_model(monkeypatch, count, status):
    events = []
    app, _ = choice_app(
        events, candidates=[Candidate(identifier="A", label="only")] * count
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("no model should be touched")

    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    with TestClient(build_app(app)) as client:
        response = client.post("/choose", json={"query": "http"})
    assert response.status_code == status
    assert [event[0] for event in events] == (
        ["find", "reserve"] if count else ["find"]
    )
    if count:
        assert response.json() == {"identifier": "A"}


def test_compatibility_plan_keeps_agent_orchestration():
    events = []
    app, _ = choice_app(events, candidates=[Candidate(identifier="A", label="only")])
    plan = _register_endpoint(app.endpoints[0], allow_direct=False)
    assert plan.result_dependent_order is None
    calls = []

    def model(messages, info):
        names = [tool.name for tool in info.function_tools]
        calls.append(names)
        if names == ["find"]:
            return ModelResponse(parts=[ToolCallPart("find", {})])
        if names:
            token = info.function_tools[0].parameters_json_schema["properties"]["item"][
                "enum"
            ][0]
            return ModelResponse(parts=[ToolCallPart("reserve", {"item": token})])
        return ModelResponse(parts=[TextPart("done")])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"query": "old"})
    )
    assert result.identifier == "A"
    assert calls == [["find"], ["reserve"], []]


def test_concurrent_handoffs_keep_tokens_and_ledgers_request_local():
    events = []
    app, _ = choice_app(events)
    domains = []

    def model(messages, info):
        if not info.function_tools:
            return ModelResponse(parts=[TextPart("done")])
        tool = info.function_tools[0]
        assert tool.name == "reserve"
        tokens = tool.parameters_json_schema["properties"]["item"]["enum"]
        domains.append(tuple(tokens))
        return ModelResponse(parts=[ToolCallPart("reserve", {"item": tokens[0]})])

    runtime = Runtime(model=FunctionModel(model))

    async def exercise():
        return await asyncio.gather(
            *(runtime.call(app.endpoints[0], {"query": str(i)}) for i in range(12))
        )

    results = asyncio.run(exercise())
    assert all(result.identifier == "A" for result in results)
    assert len(domains) == 12
    assert len({token for domain in domains for token in domain}) == 24
    assert sum(event[0] == "find" for event in events) == 12
    assert sum(event[0] == "reserve" for event in events) == 12


def test_cached_agent_is_not_touched_when_next_domain_is_singleton(monkeypatch):
    events = []
    app, candidates = choice_app(events)

    def model(messages, info):
        if not info.function_tools:
            return ModelResponse(parts=[TextPart("done")])
        tool = info.function_tools[0]
        token = tool.parameters_json_schema["properties"]["item"]["enum"][0]
        return ModelResponse(parts=[ToolCallPart("reserve", {"item": token})])

    runtime = Runtime(model=FunctionModel(model))
    asyncio.run(runtime.call(app.endpoints[0], {"query": "warm"}))
    assert runtime._agents
    candidates.pop()

    def forbidden(*args, **kwargs):
        raise AssertionError("cached agent must not mask eager resolution")

    for name in ("model_for", "_agent_for", "_build_agent"):
        monkeypatch.setattr(runtime, name, forbidden)
    result = asyncio.run(runtime.call(app.endpoints[0], {"query": "singleton"}))
    assert result.identifier == "A"
    assert sum(event[0] == "find" for event in events) == 2


@pytest.mark.parametrize("slow_sync", [False, True])
def test_prefix_deadline_prevents_consumer_and_model(monkeypatch, slow_sync):
    events = []

    def find(query: str) -> list[Candidate]:
        events.append("prefix")
        if slow_sync:
            time.sleep(0.05)
        return [Candidate(identifier="A", label="only")]

    async def async_find(query: str) -> list[Candidate]:
        events.append("prefix")
        await asyncio.sleep(0.05)
        return [Candidate(identifier="A", label="only")]

    producer = Operation(
        find if slow_sync else async_find,
        bind={"query": FromRequest("query")},
        output=list[Candidate],
    )

    def reserve(item: Candidate) -> Receipt:
        events.append("consumer")
        return Receipt(identifier=item.identifier)

    consumer = Operation(
        reserve, bind={"item": AgentChoice(from_result=producer)}, output=Receipt
    )
    app = Summon("deadline")

    @app("/deadline")
    def endpoint(
        request: Request,
        found=Required(producer, calls=Exactly(1)),
        receipt=Required(consumer, calls=Exactly(1)),
    ) -> Receipt:
        """Find and reserve the declared candidate."""
        ...

    def forbidden(*args, **kwargs):
        raise AssertionError("expired prefix must not resolve a model")

    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    app._runtime = Runtime(timeout=0.01)
    with TestClient(build_app(app)) as client:
        response = client.post("/deadline", json={"query": "slow"})
    assert response.status_code == 504
    assert events == ["prefix"]


@pytest.mark.parametrize("count", [1, 2])
def test_choice_and_suffix_share_validated_objects_and_one_run(monkeypatch, count):
    from pydantic import BaseModel

    import summonpot.runtime as runtime_module

    class Selected(BaseModel):
        identifier: str

    events = []
    observed_runs = []
    validated = {}

    def find(query: str) -> list[Candidate]:
        events.append("find")
        return [Candidate(identifier=str(i), label="candidate") for i in range(count)]

    producer = Operation(
        find, bind={"query": FromRequest("query")}, output=list[Candidate]
    )

    def choose(item: Candidate) -> Selected:
        events.append("choose")
        assert item is validated["producer"][0]
        return Selected(identifier=item.identifier)

    choice = Operation(
        choose, bind={"item": AgentChoice(from_result=producer)}, output=Selected
    )

    def finish(identifier: str) -> Receipt:
        events.append("finish")
        return Receipt(identifier=identifier)

    terminal = Operation(
        finish, bind={"identifier": FromResult(choice, "identifier")}, output=Receipt
    )
    app = Summon("suffix")

    @app("/suffix")
    def endpoint(
        request: Request,
        found=Required(producer, calls=Exactly(1)),
        selected=Required(choice, calls=Exactly(1)),
        result=Required(terminal, calls=Exactly(1)),
    ) -> Receipt:
        """Choose a declared candidate and return its finished receipt."""
        ...

    original = runtime_module._invoke_bound_operation

    async def record(tool, run, supplied, **kwargs):
        observed_runs.append(run)
        result = await original(tool, run, supplied, **kwargs)
        if tool.name == "find":
            validated["producer"] = result
        return result

    monkeypatch.setattr(runtime_module, "_invoke_bound_operation", record)
    callbacks = []

    def model(messages, info):
        names = [tool.name for tool in info.function_tools]
        callbacks.append(names)
        if names == ["choose"]:
            token = info.function_tools[0].parameters_json_schema["properties"]["item"][
                "enum"
            ][0]
            return ModelResponse(parts=[ToolCallPart("choose", {"item": token})])
        if names == ["finish"]:
            return ModelResponse(parts=[ToolCallPart("finish", {})])
        return ModelResponse(parts=[TextPart("model text cannot replace receipt")])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"query": "suffix"})
    )
    assert result == Receipt(identifier="0")
    assert events == ["find", "choose", "finish"]
    assert len(observed_runs) == 3 and all(
        run is observed_runs[0] for run in observed_runs
    )
    assert callbacks == ([] if count == 1 else [["choose"], ["finish"], []])
