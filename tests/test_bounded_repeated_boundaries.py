"""Adversarial public-runtime and HTTP boundaries for bounded repetition."""

import asyncio
import importlib.util
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from summonpot import Exactly
from summonpot.runtime import Runtime
from summonpot.server import build_app

_HELPER_SPEC = importlib.util.spec_from_file_location(
    "bounded_repeated_calls_helpers",
    Path(__file__).with_name("test_bounded_repeated_calls.py"),
)
assert _HELPER_SPEC is not None and _HELPER_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_HELPERS)
repeating_app = _HELPERS.repeating_app


def _model(proposals, starts=None):
    proposals = iter(proposals)

    def callback(messages, info):
        assert info.function_tools == []
        if starts is not None:
            starts.append(len(messages))
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(proposals))]
        )

    return FunctionModel(callback)


def _call(app, model, **kwargs):
    return asyncio.run(
        Runtime(model=model, **kwargs).call(app.endpoints[0], {"audit_id": "a-1"})
    )


def test_exactly_two_does_not_require_model_acknowledgement():
    events = []
    app = repeating_app(events, bounds=Exactly(2))
    result = _call(
        app,
        _model(
            [
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "invoke", "argument_0": "prices"},
            ]
        ),
    )
    assert events == ["stock", "prices"]
    assert result.checks == ["stock", "prices"]


def test_explicit_tool_quota_rejects_before_any_repeated_effect():
    events = []
    app = repeating_app(events, bounds=Exactly(2))
    with pytest.raises(RuntimeError, match="function-tool quota"):
        _call(
            app,
            _model([{"decision": "invoke", "argument_0": "stock"}]),
            usage_limits=UsageLimits(tool_calls_limit=1),
        )
    assert events == []


def test_wrong_choice_type_retries_without_an_application_start():
    events, callbacks = [], []
    app = repeating_app(events)
    _call(
        app,
        _model(
            [
                {"decision": "invoke", "argument_0": 17},
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "finish"},
            ],
            callbacks,
        ),
    )
    assert events == ["stock"]
    assert len(callbacks) == 3


def test_second_call_application_failure_has_no_success_fallback():
    events = []
    app = repeating_app(events, fail_on=2)
    with pytest.raises(RuntimeError, match="applicationboom"):
        _call(
            app,
            _model(
                [
                    {"decision": "invoke", "argument_0": "stock"},
                    {"decision": "invoke", "argument_0": "prices"},
                    {"decision": "finish"},
                ]
            ),
        )
    assert events == ["stock", "prices"]


def test_http_model_schema_rejection_does_not_start_operation():
    from fastapi.testclient import TestClient

    events = []
    app = repeating_app(events)
    app._runtime = Runtime(
        model=_model([{"decision": "invoke", "argument_0": 17}]), retries=0
    )
    response = TestClient(build_app(app)).post("/audit", json={"audit_id": "a-1"})
    assert response.status_code == 502
    assert events == []


def test_http_application_failure_is_500_after_two_proven_starts():
    from fastapi.testclient import TestClient

    events = []
    app = repeating_app(events, fail_on=2)
    app._runtime = Runtime(
        model=_model(
            [
                {"decision": "invoke", "argument_0": "stock"},
                {"decision": "invoke", "argument_0": "prices"},
            ]
        )
    )
    response = TestClient(build_app(app)).post("/audit", json={"audit_id": "a-1"})
    assert response.status_code == 500
    assert events == ["stock", "prices"]
