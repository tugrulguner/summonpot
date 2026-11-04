"""Public checkpoint declaration and real-runtime progression tracers."""

import asyncio
from typing import Literal

from pydantic import BaseModel, StrictBool
from pydantic_ai.models.function import FunctionModel

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


class CheckpointRequest(BaseModel):
    key: str


class CheckedStatus(BaseModel):
    key: str
    accepted: StrictBool
    revision: int


class RefreshReceipt(BaseModel):
    revision: int


class StatusReport(BaseModel):
    key: str
    accepted: bool
    revision: int


def test_already_valid_checkpoint_skips_optional_work_and_model():
    events = []

    def probe(key: str) -> CheckedStatus:
        events.append("probe")
        return CheckedStatus(key=key, accepted=True, revision=0)

    def refresh(key: str, pace: Literal["normal", "accelerated"]) -> RefreshReceipt:
        events.append("refresh")
        raise AssertionError("an accepted checkpoint must skip continuation")

    def persist(key: str, accepted: bool, revision: int) -> StatusReport:
        events.append("persist")
        return StatusReport(key=key, accepted=accepted, revision=revision)

    checked = Operation(probe, bind={"key": FromRequest("key")}, output=CheckedStatus)
    continuation = Operation(
        refresh,
        bind={"key": FromResult(checked, "key"), "pace": AgentChoice()},
        output=RefreshReceipt,
    )
    terminal = Operation(
        persist,
        bind={
            name: FromResult(checked, name, invocation="final")
            for name in ("key", "accepted", "revision")
        },
        output=StatusReport,
    )

    def forbidden_model(messages, info):
        raise AssertionError("no model request is permitted")

    class NoModelResolution(Runtime):
        def model_for(self, endpoint):
            raise AssertionError("no model configuration lookup is permitted")

    runtime = NoModelResolution(model=FunctionModel(forbidden_model))
    app = Summon("checkpoint-status", runtime=runtime)

    @app("/status")
    def endpoint(
        request: CheckpointRequest,
        result=Required(terminal, calls=Exactly(1)),
        change=Depends(continuation, calls=AtMost(2)),
        check=Required(checked, calls=Between(1, 3), until="accepted"),
    ) -> StatusReport:
        """Refresh the job only while not accepted, then persist the checked status."""
        ...

    result = asyncio.run(runtime.call(app.endpoints[0], {"key": "job-1"}))
    assert result == StatusReport(key="job-1", accepted=True, revision=0)
    assert events == ["probe", "persist"]
