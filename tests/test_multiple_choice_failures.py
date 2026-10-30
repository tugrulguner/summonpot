"""Multi-frontier failures preserve the existing deadline and effect boundaries."""

import asyncio
import time

import pytest
from test_multiple_choice_adversarial import Input, Item, Result, scripted, staged_chain

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime


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


def test_provider_failure_after_two_local_operations_preserves_the_prefix(monkeypatch):
    events = []
    app = staged_chain((1, 2), events)

    def unavailable(*args, **kwargs):
        assert events == ["find", "step1"]
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(Runtime, "model_for", unavailable)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(Runtime().call(app.endpoints[0], {"query": "q"}))
    assert events == ["find", "step1"]


@pytest.mark.parametrize("synchronous", [False, True])
@pytest.mark.parametrize("multi", [False, True])
def test_later_producer_deadline_never_starts_next_consumer_or_model(
    monkeypatch, synchronous, multi
):
    events, runs = [], []

    def first(query: str) -> list[Item]:
        events.append("first")
        return [Item(key=query)]

    a = Operation(first, bind={"query": FromRequest("query")}, output=list[Item])

    async def async_later(item: Item) -> list[Item]:
        events.append("later-start")
        await asyncio.sleep(0.08)
        events.append("later-end")
        return [item, Item(key="extra")] if multi else [item]

    def sync_later(item: Item) -> list[Item]:
        events.append("later-start")
        time.sleep(0.08)
        events.append("later-end")
        return [item, Item(key="extra")] if multi else [item]

    b = Operation(
        sync_later if synchronous else async_later,
        bind={"item": AgentChoice(from_result=a)},
        output=list[Item],
    )

    def finish(item: Item) -> Result:
        events.append("finish")
        return Result(key=item.key)

    c = Operation(finish, bind={"item": AgentChoice(from_result=b)}, output=Result)
    app = Summon("deadline")

    @app("/deadline")
    def endpoint(
        request: Input,
        a=Required(a, calls=Exactly(1)),
        b=Required(b, calls=Exactly(1)),
        c=Required(c, calls=Exactly(1)),
    ) -> Result:
        """Finish the selected result."""
        ...

    import summonpot.runtime as module

    original = module._new_run

    def capture(*args):
        run = original(*args)
        runs.append(run)
        return run

    monkeypatch.setattr(module, "_new_run", capture)

    def forbidden(*args, **kwargs):
        raise AssertionError("deadline must prevent model entry")

    monkeypatch.setattr(Runtime, "_agent_for", forbidden)

    async def check():
        with pytest.raises(TimeoutError):
            await Runtime(timeout=0.02).call(app.endpoints[0], {"query": "q"})
        await asyncio.sleep(0.1)

    asyncio.run(check())
    assert events[:2] == ["first", "later-start"]
    assert "finish" not in events
    assert ("later-end" in events) is synchronous
    assert runs[0].states[1].started == 1
    assert runs[0].states[1].outcome == "outcome_unknown"
    assert runs[0].states[2].started == 0


def test_agent_cannot_finalize_before_the_remaining_required_operation():
    events, attempts = [], []
    app = staged_chain((1, 2), events)
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    def fake_final(messages, info):
        attempts.append([tool.name for tool in info.function_tools])
        return ModelResponse(parts=[TextPart("I completed the receipt")])

    from fastapi.testclient import TestClient

    from summonpot.server import build_app

    app._runtime = Runtime(model=FunctionModel(fake_final))
    with TestClient(build_app(app)) as client:
        response = client.post("/staged", json={"query": "q"})
    assert response.status_code == 502
    assert events == ["find", "step1"]
    assert attempts and all(names == ["finish"] for names in attempts)


def test_new_runtime_call_reexecutes_prefix_without_framework_resume():
    events, rounds = [], []
    app = staged_chain((1, 2), events)
    runtime = Runtime(model=scripted(events, rounds))
    first = asyncio.run(runtime.call(app.endpoints[0], {"query": "q"}))
    second = asyncio.run(runtime.call(app.endpoints[0], {"query": "q"}))
    assert first == second
    assert events.count("find") == events.count("step1") == events.count("finish") == 2
