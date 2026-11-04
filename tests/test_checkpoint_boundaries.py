"""Authority and failure controls through an actual registered checkpoint run."""

import asyncio
import json
from typing import Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits
from test_checkpoint_continuation import application

import summonpot.runtime as runtime_module
from summonpot import AtMost
from summonpot.runtime import Runtime


def test_selection_cannot_cross_its_captured_round_epoch(monkeypatch):
    app, state, _, _ = application(target=2)
    captured = []
    original = runtime_module._invoke_bound_operation

    async def capture(tool, run, supplied, **kwargs):
        if not captured:
            captured.append(run)
        return await original(tool, run, supplied, **kwargs)

    def changed_round(messages, info):
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        assert isinstance(text, str)
        data = json.loads(text[text.index('{"decision_slot_') :])
        selected = {
            slot: domain["candidates"][0]["token"] for slot, domain in data.items()
        }
        captured[0].checkpoint_epoch += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, selected)])

    monkeypatch.setattr(runtime_module, "_invoke_bound_operation", capture)
    app._runtime._model = FunctionModel(changed_round)
    with pytest.raises(RuntimeError):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert state["value"] == 0


def test_usage_budget_spans_rounds_and_leaves_effect_without_terminal():
    app, state, events, turns = application(target=9)
    app._runtime.usage_limits = UsageLimits(request_limit=1)
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert state["value"] == 1 and len(turns) == 1
    assert events == [("probe", 0), ("advance", "A", "normal"), ("probe", 1)]


def test_previous_round_token_cannot_authorize_next_start():
    app, state, events, _ = application(target=9)
    old = []

    def replay(messages, info):
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        assert isinstance(text, str)
        data = json.loads(text[text.index('{"decision_slot_') :])
        slot, domain = next(iter(data.items()))
        if not old:
            old.append(domain["candidates"][0]["token"])
        else:
            assert old[0] not in {c["token"] for c in domain["candidates"]}
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {slot: old[0]})]
        )

    app._runtime._model = FunctionModel(replay)
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert state["value"] == 1 and events[-1] == ("probe", 1)
    assert not any(e[0] == "persist" for e in events)


def test_mutable_inspection_metadata_does_not_change_compiled_contract():
    app, state, events, turns = application(target=9)
    for tool in app.endpoints[0].tools:
        tool.until = "revision"
        tool.bounds = AtMost(100)
        tool.fn = lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("mutated callable ran")
        )
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert result.accepted is False and result.revision == 2
    assert state["value"] == 2 and len(turns) == 2 and events[-1] == ("persist", 2)


def test_model_configuration_resolves_once_across_multiple_rounds():
    app, _, _, turns = application(target=2)
    configured = app._runtime._model
    lookups = []

    class Observed(Runtime):
        def model_for(self, endpoint: Any):
            lookups.append(1)
            assert len(lookups) == 1
            return super().model_for(endpoint)

    app._runtime = Observed(model=configured, retries=0)
    assert (
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"})).accepted is True
    )
    assert len(lookups) == 1 and len(turns) == 2


def test_concurrent_same_round_admission_has_one_winner(monkeypatch):
    app, state, _, _ = application(target=2)
    original = runtime_module._invoke_bound_operation
    raced = []

    async def intercept(tool, run, supplied, **kwargs):
        if tool.name == "advance" and not raced:
            raced.append(True)
            outcomes = await asyncio.gather(
                original(tool, run, supplied, **kwargs),
                original(tool, run, supplied, **kwargs),
                return_exceptions=True,
            )
            successful = [
                value for value in outcomes if not isinstance(value, BaseException)
            ]
            assert len(successful) == 1
            assert sum(isinstance(value, RuntimeError) for value in outcomes) == 1
            return successful[0]
        return await original(tool, run, supplied, **kwargs)

    monkeypatch.setattr(runtime_module, "_invoke_bound_operation", intercept)
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert result.accepted is True and state["value"] == 2 and raced == [True]


def test_timeout_during_selection_aborts_without_next_effect(monkeypatch):
    app, state, events, _ = application(target=2)
    entered = asyncio.Event()
    captured = []
    original = runtime_module._invoke_bound_operation

    async def capture(tool, run, supplied, **kwargs):
        if not captured:
            captured.append(run)
        return await original(tool, run, supplied, **kwargs)

    async def blocked(messages, info) -> ModelResponse:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("blocked fixture unexpectedly resumed")

    monkeypatch.setattr(runtime_module, "_invoke_bound_operation", capture)
    app._runtime = Runtime(model=FunctionModel(blocked), timeout=1, retries=0)

    async def check():
        task = asyncio.create_task(app._runtime.call(app.endpoints[0], {"key": "A"}))
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task, timeout=3)

    asyncio.run(check())
    assert state["value"] == 0 and events == [("probe", 0)]
    assert captured[0].checkpoint_aborted and captured[0].checkpoint_expected is None
    assert all(s.running == 0 for s in captured[0].states)
