"""Public-runtime regressions for bounded repeated calls."""

import asyncio
from typing import Literal

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from summonpot import AgentChoice, Between, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime


class Request(BaseModel):
    audit_id: str


class Snapshot(BaseModel):
    checks: list[str]


def repeating_app(events, bounds=None, fail_on=None, returned=None):
    def inspect(audit_id: str, check: Literal["stock", "prices"]) -> Snapshot:
        assert audit_id == "a-1"
        events.append(check)
        if len(events) == fail_on:
            raise RuntimeError("applicationboom")
        result = Snapshot(checks=events.copy())
        if returned is not None:
            returned.append(result)
        return result

    op = Operation(
        inspect,
        bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
        output=Snapshot,
    )
    app = Summon("bounded-repeated-calls")

    @app("/audit")
    def audit(
        request: Request, result=Required(op, calls=bounds or Between(1, 3))
    ) -> Snapshot:
        """Inspect relevant inventory checks and return the final snapshot."""
        ...

    return app


def scripted(proposals, callbacks=None):
    proposals = iter(proposals)

    def model(messages, info):
        assert info.function_tools == []
        assert len(info.output_tools) == 1
        assert info.instructions and "fixed endpoint goal" in info.instructions.lower()
        schema = info.output_tools[0].parameters_json_schema
        assert set(schema["properties"]) == {"decision", "argument_0"}
        if callbacks is not None:
            callbacks.append(messages)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(proposals))]
        )

    return FunctionModel(model)


def test_bounded_repetition_returns_final_successful_operation_result(monkeypatch):
    import summonpot.runtime as module

    events, returned, runs, callbacks = [], [], [], []
    app = repeating_app(events, returned=returned)
    original = module._new_run

    def capture(*args):
        run = original(*args)
        runs.append(run)
        return run

    monkeypatch.setattr(module, "_new_run", capture)
    runtime = Runtime(
        model=scripted(
            [
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "invoke", "argument_0": "prices"},
                {"decision": "finish"},
            ],
            callbacks,
        )
    )
    result = asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "a-1"}))
    assert events == ["stock", "prices"] and len(callbacks) == 3
    assert result.checks == ["stock", "prices"]
    state = runs[0].states[0]
    assert result is state.invocations[-1].result is state.result
    assert (state.started, state.succeeded) == (2, 2)
    assert [i.ordinal for i in state.invocations] == [1, 2]
    assert all(i.outcome == "succeeded" for i in state.invocations)
    assert all(
        i.result == output
        for i, output in zip(state.invocations, returned, strict=True)
    )


def test_repeated_operation_failure_does_not_fall_back_to_prior_success():
    events = []
    app = repeating_app(events, fail_on=2)
    runtime = Runtime(
        model=scripted(
            [
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "invoke", "argument_0": "prices"},
            ]
        )
    )
    with pytest.raises(RuntimeError, match="applicationboom"):
        asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "a-1"}))
    assert events == ["stock", "prices"]


def test_premature_finish_correction_does_not_count_as_start():
    events, callbacks = [], []
    app = repeating_app(events)
    runtime = Runtime(
        model=scripted(
            [
                {"decision": "finish"},
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "finish"},
            ],
            callbacks,
        )
    )
    result = asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "a-1"}))
    assert result.checks == ["stock"] and events == ["stock"] and len(callbacks) == 3


def test_tool_quota_rejected_before_model_or_application(monkeypatch):
    events = []
    app = repeating_app(events)

    def forbidden(*args, **kwargs):
        raise AssertionError("configured quota must fail before model resolution")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    with pytest.raises(RuntimeError, match="function-tool quota"):
        asyncio.run(
            Runtime(usage_limits=UsageLimits(tool_calls_limit=2)).call(
                app.endpoints[0], {"audit_id": "a-1"}
            )
        )
    assert events == []
