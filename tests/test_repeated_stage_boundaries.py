"""Adversarial public-runtime boundaries for closed repeated stages."""

import asyncio

import pytest
from test_repeated_stage import stage_app


def run(runtime, app):
    return asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "audit-1"}))


def test_failed_second_producer_does_not_fall_back_to_first_snapshot():
    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "invoke", "argument_0": "prices"},
            {"decision": "finish"},
        ],
        fail_at=2,
    )

    with pytest.raises(ValueError, match="application failure"):
        run(runtime, app)

    assert events == [
        ("inspect", "audit-1", "stock"),
        ("inspect", "audit-1", "prices"),
    ]


def test_premature_finish_retries_under_minimum():
    from summonpot import Between

    app, runtime, events = stage_app(
        [
            {"decision": "finish"},
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "invoke", "argument_0": "prices"},
            {"decision": "finish"},
        ],
        bounds=Between(2, 3),
    )
    runtime.retries = 1
    assert run(runtime, app).final_check == "prices"
    assert len(events) == 3 and events[-1][0] == "report"


def test_request_budget_is_shared_across_decisions():
    from pydantic_ai.exceptions import UsageLimitExceeded

    from summonpot import UsageLimits

    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "finish"},
        ],
        runtime_options={"usage_limits": UsageLimits(request_limit=1)},
    )
    with pytest.raises(UsageLimitExceeded):
        run(runtime, app)
    assert events == [("inspect", "audit-1", "stock")]


def test_explicit_tool_quota_rejects_before_work():
    from summonpot import UsageLimits

    app, runtime, events = stage_app(
        [], runtime_options={"usage_limits": UsageLimits(tool_calls_limit=3)}
    )
    with pytest.raises(RuntimeError, match="quota is unsupported"):
        run(runtime, app)
    assert events == []


def test_final_receiving_constraint_fails_before_terminal_start():
    import summonpot.runtime as kernel

    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "finish"},
        ],
        check_constraint=True,
    )
    with pytest.raises(kernel._OperationInputError):
        run(runtime, app)
    assert events == [("inspect", "audit-1", "stock")]


@pytest.mark.parametrize("failure", ["terminal_failure", "terminal_invalid"])
def test_terminal_failure_has_no_snapshot_fallback(failure):
    import summonpot.runtime as kernel

    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "finish"},
        ],
        **{failure: True},
    )
    expected = (
        ValueError if failure == "terminal_failure" else kernel._OperationOutputError
    )
    with pytest.raises(expected):
        run(runtime, app)
    assert events == [("inspect", "audit-1", "stock"), ("report", "audit-1", "stock")]


@pytest.mark.parametrize("operation", ["inspect", "report"])
def test_one_deadline_spans_stage_and_terminal(operation, monkeypatch):
    import time

    import summonpot.runtime as kernel

    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "finish"},
        ],
        runtime_options={"timeout": 30},
    )
    original = kernel._call_capability
    deadlines = []

    async def expire_after_actual_operation(fn, *args, **kwargs):
        deadlines.append(kernel._runtime_deadline.get())
        result = await original(fn, *args, **kwargs)
        if fn.__name__ == operation:
            # Deterministically exhaust the same absolute budget after the target
            # really starts/completes, not during slow CI model preparation.
            kernel._runtime_deadline.set(time.monotonic() - 1)
        return result

    monkeypatch.setattr(kernel, "_call_capability", expire_after_actual_operation)
    with pytest.raises(TimeoutError):
        run(runtime, app)
    assert events[0] == ("inspect", "audit-1", "stock")
    assert len(events) == (1 if operation == "inspect" else 2)
    assert deadlines[0] is not None and len(set(deadlines)) == 1
