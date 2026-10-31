"""Kernel-level closure probes; public requests still execute the real runtime."""

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from pydantic_ai.exceptions import ModelRetry
from test_repeated_stage import StageReport, StageSnapshot, stage_app

import summonpot.runtime as kernel


def test_frozen_closure_pins_ordinal_and_ignores_mutable_legacy_result(monkeypatch):
    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "invoke", "argument_0": "prices"},
            {"decision": "finish"},
        ]
    )
    original = kernel._invoke_bound_operation
    observed = []

    async def inspect_kernel(tool, run, supplied, **kwargs):
        if not tool.repeated:
            plan = runtime._plan_for(app.endpoints[0])
            assert plan.repeated_tool is not None and plan.repeated_terminal is not None
            state = run.states[plan.repeated_tool]
            closed = state.closed
            assert closed is not None
            assert closed.producer_identity == plan.repeated_tool
            assert closed.ordinal == 2
            assert closed.result is state.invocations[-1].result
            with pytest.raises(FrozenInstanceError):
                closed.ordinal = 1
            state.result = StageSnapshot(audit_id="forged-legacy-slot", check="stock")
            output = await original(tool, run, supplied, **kwargs)
            with pytest.raises(kernel._OperationExecutionError):
                await original(
                    plan.tools[plan.repeated_tool], run, {"check": "stock"}, **kwargs
                )
            observed.append(closed.ordinal)
            return output
        # A prior successful invocation must not make this terminal ready.
        plan = runtime._plan_for(app.endpoints[0])
        assert plan.repeated_terminal is not None
        with pytest.raises(ModelRetry):
            await original(plan.tools[plan.repeated_terminal], run, {}, **kwargs)
        return await original(tool, run, supplied, **kwargs)

    monkeypatch.setattr(kernel, "_invoke_bound_operation", inspect_kernel)
    result = asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "pinned"}))
    assert result == StageReport(audit_id="pinned", final_check="prices")
    assert observed == [2]
    assert events == [
        ("inspect", "pinned", "stock"),
        ("inspect", "pinned", "prices"),
        ("report", "pinned", "prices"),
    ]


def test_automatic_maximum_closes_without_another_model_turn():
    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "invoke", "argument_0": "prices"},
            {"decision": "invoke", "argument_0": "stock"},
        ]
    )
    result = asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "max"}))
    assert result.final_check == "stock"
    assert len(events) == 4 and events[-1] == ("report", "max", "stock")
