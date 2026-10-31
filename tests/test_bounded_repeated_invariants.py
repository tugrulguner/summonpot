"""Budgets, invalid decisions and deadline uncertainty for repeated invocation."""

import asyncio
import json
import threading
from typing import Literal

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage, UsageLimits
from test_bounded_repeated_calls import Request, Snapshot, repeating_app, scripted

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime


def test_request_limit_spans_invocations_and_cannot_return_partial_success():
    events = []
    app = repeating_app(events, bounds=Exactly(2))
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(
            Runtime(
                model=scripted([{"decision": "invoke", "argument_0": "stock"}]),
                usage_limits=UsageLimits(request_limit=1),
            ).call(app.endpoints[0], {"audit_id": "a-1"})
        )
    assert events == ["stock"]


def test_default_usage_limits_and_model_are_shared(monkeypatch):
    events, captures, resolutions = [], [], []
    app = repeating_app(events)
    original = Runtime._select_repeated_decision
    original_model = Runtime.model_for

    async def capture(self, plan, tool, run, request, model, usage, limits):
        captures.append((usage, limits, usage.requests))
        return await original(self, plan, tool, run, request, model, usage, limits)

    def resolve(self, endpoint):
        resolutions.append(endpoint)
        return original_model(self, endpoint)

    monkeypatch.setattr(Runtime, "_select_repeated_decision", capture)
    monkeypatch.setattr(Runtime, "model_for", resolve)
    result = asyncio.run(
        Runtime(
            model=scripted(
                [
                    {"decision": "invoke", "argument_0": "stock"},
                    {"decision": "invoke", "argument_0": "prices"},
                    {"decision": "finish"},
                ]
            )
        ).call(app.endpoints[0], {"audit_id": "a-1"})
    )
    assert result.checks == ["stock", "prices"] and len(resolutions) == 1
    assert [c[2] for c in captures] == [0, 1, 2]
    assert all(c[0] is captures[0][0] and c[1] is captures[0][1] for c in captures)
    assert captures[0][1].request_limit == UsageLimits().request_limit
    assert captures[0][0].requests == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "invoke"},
        {"decision": "invoke", "argument_0": "unknown"},
        {"decision": "invoke", "argument_0": True},
        {"decision": "invoke", "argument_0": "stock", "audit_id": "forged"},
        {"decision": "finish", "argument_0": "stock"},
    ],
)
def test_invalid_decision_never_reserves_an_application_start(payload, monkeypatch):
    import summonpot.runtime as module

    events, runs = [], []
    app = repeating_app(events)
    original = module._new_run

    def capture(*args):
        run = original(*args)
        runs.append(run)
        return run

    monkeypatch.setattr(module, "_new_run", capture)
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(
            Runtime(model=scripted([payload]), retries=0).call(
                app.endpoints[0], {"audit_id": "a-1"}
            )
        )
    assert events == [] and runs[0].states[0].started == 0
    assert runs[0].states[0].invocations == []


def test_total_token_budget_is_not_reset_after_first_invocation():
    events = []
    app = repeating_app(events, bounds=Exactly(2))

    def model(messages, info):
        assert not info.function_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"decision": "invoke", "argument_0": "stock"},
                )
            ],
            usage=RequestUsage(input_tokens=5, output_tokens=3),
        )

    with pytest.raises(UsageLimitExceeded):
        asyncio.run(
            Runtime(
                model=FunctionModel(model),
                usage_limits=UsageLimits(total_tokens_limit=10),
            ).call(app.endpoints[0], {"audit_id": "a-1"})
        )
    assert events == ["stock"]


def test_provider_failure_after_two_successes_does_not_finalize_earlier_result():
    events = []
    app = repeating_app(events)

    def model(messages, info):
        starts = json.loads(messages[0].parts[0].content)["starts"]
        if starts == 2:
            raise RuntimeError("providerboom")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"decision": "invoke", "argument_0": ("stock", "prices")[starts]},
                )
            ]
        )

    with pytest.raises(RuntimeError, match="providerboom"):
        asyncio.run(
            Runtime(model=FunctionModel(model)).call(
                app.endpoints[0], {"audit_id": "a-1"}
            )
        )
    assert events == ["stock", "prices"]


def test_multiple_output_proposals_do_not_dispatch_multiple_operations():
    events, callbacks = [], []
    app = repeating_app(events)

    def model(messages, info):
        assert not info.function_tools
        callbacks.append(messages)
        payloads = (
            [
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "invoke", "argument_0": "prices"},
            ]
            if len(callbacks) == 1
            else [{"decision": "finish"}]
        )
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, p, tool_call_id=f"c{i}")
                for i, p in enumerate(payloads)
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"audit_id": "a-1"})
    )
    assert result.checks == ["stock"] and events == ["stock"] and len(callbacks) == 2


def test_late_sync_effect_keeps_uncertain_reservation_and_never_starts_again(
    monkeypatch,
):
    import summonpot.runtime as module

    started, release, done = threading.Event(), threading.Event(), threading.Event()
    events, runs = [], []

    def inspect(audit_id: str, check: Literal["stock"]) -> Snapshot:
        started.set()
        release.wait(2)
        events.append(check)
        done.set()
        return Snapshot(checks=events.copy())

    op = Operation(
        inspect,
        bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
        output=Snapshot,
    )
    app = Summon("late-sync")

    @app("/late")
    def endpoint(request: Request, result=Required(op, calls=Exactly(2))) -> Snapshot:
        """Perform bounded stock checks and return a canonical snapshot."""
        ...

    original = module._new_run

    def capture(*args):
        run = original(*args)
        runs.append(run)
        return run

    monkeypatch.setattr(module, "_new_run", capture)

    async def exercise():
        runtime = Runtime(
            model=scripted([{"decision": "invoke", "argument_0": "stock"}]), timeout=0.2
        )
        task = asyncio.create_task(runtime.call(app.endpoints[0], {"audit_id": "a-1"}))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            with pytest.raises(TimeoutError):
                await task
            state = runs[0].states[0]
            assert (state.started, state.succeeded) == (1, 0)
            assert state.invocations[0].outcome == "outcome_unknown"
        finally:
            release.set()
        assert await asyncio.to_thread(done.wait, 1)
        assert state.succeeded == 0 and state.invocations[0].result is None

    asyncio.run(exercise())
    assert events == ["stock"]
