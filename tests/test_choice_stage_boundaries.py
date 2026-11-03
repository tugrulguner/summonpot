"""Cross-phase accounting and canonical authority for choice/stage composition."""

import asyncio
from typing import Any, cast

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits
from test_choice_stage import Report, application

import summonpot.runtime as kernel


def test_selection_receives_the_canonical_producer_member(monkeypatch):
    captured = []
    original = kernel._new_run

    def capture(*args, **kwargs):
        run = original(*args, **kwargs)
        captured.append(run)
        return run

    monkeypatch.setattr(kernel, "_new_run", capture)
    app, _events, _turns, _resolved, selected = application(selected_index=1)
    output = asyncio.run(app._runtime.call(app.endpoints[0], {"category": "canonical"}))
    assert output == Report(identifier="canonical-1", check="prices")
    assert len(captured) == 1
    assert selected[0] is captured[0].states[0].result[1]
    assert captured[0].states[2].closed.ordinal == 2
    assert captured[0].states[3].result is output


def test_model_configuration_is_not_reread_after_selection(monkeypatch):
    app, _events, turns, resolved, _ = application()
    original = kernel._call_capability

    async def observe(fn, *args, **kwargs):
        result = await original(fn, *args, **kwargs)
        if fn.__name__ == "select":
            app._runtime._model = "invalid-provider:changed-after-selection"
        return result

    monkeypatch.setattr(kernel, "_call_capability", observe)
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"category": "fixed"}))
    assert result.identifier == "fixed-1"
    assert resolved == [1]
    assert turns == ["selection", "check", "check", "check"]


def test_selection_request_consumes_the_stage_request_budget():
    app, events, turns, resolved, _ = application(
        runtime_options={"usage_limits": UsageLimits(request_limit=2)}
    )
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "budget"}))
    assert turns == ["selection", "check"]
    assert events == ["find", ("select", "budget-1"), ("inspect", "budget-1", "stock")]
    assert resolved == [1]


def test_every_repeated_start_rechecks_the_selected_prefix_result(monkeypatch):
    app, events, turns, _resolved, _ = application()
    original = kernel._call_capability
    selected = []
    new_run = kernel._new_run

    def capture(*args, **kwargs):
        run = new_run(*args, **kwargs)
        selected.append(run)
        return run

    monkeypatch.setattr(kernel, "_new_run", capture)

    async def observe(fn, *args, **kwargs):
        result = await original(fn, *args, **kwargs)
        if fn.__name__ == "inspect":
            # Trusted application corruption is a receiving-validation probe,
            # not a claim that the model can mutate canonical server objects.
            selected[0].states[1].result.identifier = cast(Any, 42)
        return result

    monkeypatch.setattr(kernel, "_call_capability", observe)
    with pytest.raises(kernel._OperationInputError):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "receiving"}))
    assert events == [
        "find",
        ("select", "receiving-1"),
        ("inspect", "receiving-1", "stock"),
    ]
    assert turns == ["selection", "check", "check"]


def test_selection_correction_charges_the_shared_request_budget():
    app, events, _, resolved, _ = application(
        runtime_options={"usage_limits": UsageLimits(request_limit=2)}
    )
    assert isinstance(app._runtime._model, FunctionModel)
    original = app._runtime._model.function
    assert original is not None
    attempts = []

    def respond(messages, info):
        attempts.append(1)
        if len(attempts) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name, {"decision_slot_0": "forged-token"}
                    )
                ]
            )
        return original(messages, info)

    app._runtime._model = FunctionModel(respond)
    app._runtime.retries = 1
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "corrected"}))
    assert len(attempts) == 2
    assert events == ["find", ("select", "corrected-1")]
    assert resolved == [1]


def test_stage_selector_cannot_override_selected_identifier():
    app, events, _, _, _ = application()
    assert isinstance(app._runtime._model, FunctionModel)
    original = app._runtime._model.function
    assert original is not None

    def respond(messages, info):
        props = info.output_tools[0].parameters_json_schema["properties"]
        if "decision" in props:
            assert set(props) == {"decision", "argument_0"}
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "decision": "invoke",
                            "argument_0": "stock",
                            "identifier": "different-supplier",
                        },
                    )
                ]
            )
        return original(messages, info)

    app._runtime._model = FunctionModel(respond)
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "bounded"}))
    assert events == ["find", ("select", "bounded-1")]


def test_default_request_limit_is_shared_after_selection_corrections():
    app, events, _, resolved, _ = application()
    cap = UsageLimits().request_limit
    assert cap is not None and cap > 1
    assert isinstance(app._runtime._model, FunctionModel)
    original = app._runtime._model.function
    assert original is not None
    attempts = []

    def respond(messages, info):
        attempts.append(1)
        if len(attempts) < cap:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name, {"decision_slot_0": "forged-token"}
                    )
                ]
            )
        return original(messages, info)

    app._runtime._model = FunctionModel(respond)
    app._runtime.retries = cap + 1
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "default"}))
    assert len(attempts) == cap
    assert events == ["find", ("select", "default-1")]
    assert resolved == [1]
