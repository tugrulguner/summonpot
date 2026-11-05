"""Public continuation and same-round boundary checks."""

import asyncio
import json
from typing import Literal

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from test_checkpoint import (
    CheckedStatus,
    CheckpointRequest,
    RefreshReceipt,
    StatusReport,
)

from summonpot import (
    AgentChoice,
    AtMost,
    Between,
    Depends,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime


def application(target=2, *, crossing=False):
    state = {"value": 0}
    events = []
    turns = []

    def probe(key: str) -> CheckedStatus:
        events.append(("probe", state["value"]))
        return CheckedStatus(
            key=key, accepted=state["value"] >= target, revision=state["value"]
        )

    def advance(key: str, pace: Literal["normal", "accelerated"]) -> RefreshReceipt:
        events.append(("advance", key, pace))
        state["value"] += 1 if pace == "normal" else 2
        return RefreshReceipt(revision=state["value"])

    def persist(key: str, accepted: bool, revision: int) -> StatusReport:
        events.append(("persist", revision))
        return StatusReport(key=key, accepted=accepted, revision=revision)

    a = Operation(probe, bind={"key": FromRequest("key")}, output=CheckedStatus)
    c = Operation(
        persist,
        bind={
            name: FromResult(a, name, invocation="final")
            for name in ("key", "accepted", "revision")
        },
        output=StatusReport,
    )
    b = Operation(
        advance,
        bind={"key": FromResult(c if crossing else a, "key"), "pace": AgentChoice()},
        after=(a,) if crossing else (),
        output=RefreshReceipt,
    )

    def model(messages, info):
        assert not info.function_tools
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        assert isinstance(text, str)
        data = json.loads(text[text.index('{"decision_slot_') :])
        arguments = {
            slot: next(
                v["token"] for v in definition["candidates"] if v["value"] == "normal"
            )
            for slot, definition in data.items()
        }
        turns.append(arguments)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, arguments)])

    app = Summon(
        "checkpoint-continuation",
        runtime=Runtime(model=FunctionModel(model), retries=0),
    )

    @app("/status")
    def endpoint(
        request: CheckpointRequest,
        status=Required(a, calls=Between(1, 3), until="accepted"),
        terminal=Required(c, calls=Exactly(1)),
        step=Depends(b, calls=AtMost(2)),
    ) -> StatusReport:
        """Advance using normal pace until accepted or the declared limit, then return verified facts."""
        ...

    return app, state, events, turns


@pytest.mark.parametrize("target,accepted", [(2, True), (9, False)])
def test_negative_rounds_stop_or_exhaust_without_model_finish(target, accepted):
    app, state, events, turns = application(target)
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "job-A"}))
    assert result == StatusReport(key="job-A", accepted=accepted, revision=2)
    assert state["value"] == 2 and len(turns) == 2
    assert events == [
        ("probe", 0),
        ("advance", "job-A", "normal"),
        ("probe", 1),
        ("advance", "job-A", "normal"),
        ("probe", 2),
        ("persist", 2),
    ]


def test_negative_region_cannot_read_terminal_output():
    application()  # Positive registration control.
    with pytest.raises(TypeError):
        application(crossing=True)
