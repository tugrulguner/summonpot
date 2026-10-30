"""Adversarial boundary tests for framework-owned decision progression."""

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime

_spec = importlib.util.spec_from_file_location(
    "_decision_progression_adversarial_helpers",
    Path(__file__).with_name("test_multiple_choice_adversarial.py"),
)
assert _spec is not None and _spec.loader is not None
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
staged_chain = _helpers.staged_chain


def _decision_payload(messages: Any) -> dict[str, Any]:
    contents = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            content = getattr(part, "content", None)
            if isinstance(content, str):
                contents.append(content)
    for content in reversed(contents):
        for line in reversed(content.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and any(
                key.startswith("decision_slot_") for key in payload
            ):
                return payload
    raise AssertionError("selector prompt omitted structured candidate evidence")


def _tokens(messages: Any) -> list[str]:
    payload = _decision_payload(messages)
    return [
        candidate["token"]
        for slot in payload.values()
        for candidate in slot["candidates"]
    ]


def test_selector_rejects_extra_slot_before_consumer_then_corrects_stably():
    events: list[str] = []
    app = staged_chain([2, 1], events)
    endpoint = app.endpoints[0]
    seen: list[list[str]] = []

    def choose(messages, info):
        assert info.function_tools == []
        assert len(info.output_tools) == 1
        tokens = _tokens(messages)
        assert tokens
        seen.append(tokens)
        fields = info.output_tools[0].parameters_json_schema["properties"]
        payload = {next(iter(fields)): tokens[0]}
        if len(seen) == 1:
            payload["unexpected"] = tokens[0]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    result = asyncio.run(
        Runtime(model=FunctionModel(choose), retries=1).call(endpoint, {"query": "q"})
    )
    assert result.key.startswith("q-")
    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert events.count("find") == 1
    assert events.count("step1") == 1
    assert events.count("finish") == 1


@pytest.mark.parametrize("bad", ["forged", True, 17])
def test_selector_rejects_nonmember_or_wrong_type_without_consumer_start(bad):
    events: list[str] = []
    app = staged_chain([2, 1], events)
    endpoint = app.endpoints[0]
    attempts = 0

    def choose(messages, info):
        nonlocal attempts
        assert info.function_tools == []
        attempts += 1
        field = next(iter(info.output_tools[0].parameters_json_schema["properties"]))
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {field: bad})]
        )

    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(
            Runtime(model=FunctionModel(choose), retries=0).call(
                endpoint, {"query": "q"}
            )
        )
    assert attempts == 1
    assert events.count("find") == 1
    assert "step1" not in events
    assert "finish" not in events
