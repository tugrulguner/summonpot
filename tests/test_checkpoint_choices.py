"""Actual producer-backed domains at a bounded checkpoint frontier."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits
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
from summonpot.server import build_app


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action: str


def domain(messages):
    text = next(
        p.content
        for m in reversed(messages)
        for p in m.parts
        if isinstance(p, UserPromptPart)
    )
    assert isinstance(text, str)
    return json.loads(text[text.index('{"decision_slot_') :])


def choose(messages, info, *, invalid=False, extra=False):
    assert not info.function_tools
    arguments = {
        slot: ("forged" if invalid else data["candidates"][0]["token"])
        for slot, data in domain(messages).items()
    }
    if extra:
        arguments["key"] = "injected"
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, arguments)])


def application(values, callback=None, *, retries=0, limits=None):
    events, received, lookups = [], [], []
    state = {"revision": 0}

    def probe(key: str) -> CheckedStatus:
        events.append("probe")
        return CheckedStatus(
            key=key, accepted=state["revision"] > 0, revision=state["revision"]
        )

    def candidates(key: str) -> list[Candidate]:
        events.append("candidates")
        return values

    def apply(candidate: Candidate) -> RefreshReceipt:
        events.append("apply")
        received.append(candidate)
        state["revision"] += 1
        return RefreshReceipt(revision=state["revision"])

    def persist(key: str, accepted: bool, revision: int) -> StatusReport:
        events.append("persist")
        return StatusReport(key=key, accepted=accepted, revision=revision)

    check = Operation(probe, bind={"key": FromRequest("key")}, output=CheckedStatus)
    producer = Operation(
        candidates, bind={"key": FromResult(check, "key")}, output=list[Candidate]
    )
    consumer = Operation(
        apply,
        bind={"candidate": AgentChoice(from_result=producer)},
        output=RefreshReceipt,
    )
    terminal = Operation(
        persist,
        bind={
            name: FromResult(check, name, invocation="final")
            for name in ("key", "accepted", "revision")
        },
        output=StatusReport,
    )

    class Observed(Runtime):
        def model_for(self, endpoint):
            lookups.append(1)
            return super().model_for(endpoint)

    def forbidden(messages, info):
        raise AssertionError("no decision permitted")

    app = Summon(
        "candidate-checkpoint",
        runtime=Observed(
            model=FunctionModel(callback or forbidden),
            retries=retries,
            usage_limits=limits,
        ),
    )

    @app("/status")
    def endpoint(
        request: CheckpointRequest,
        checked=Required(check, calls=Between(1, 3), until="accepted"),
        options=Depends(producer, calls=AtMost(2)),
        changed=Depends(consumer, calls=AtMost(2)),
        report=Required(terminal, calls=Exactly(1)),
    ) -> StatusReport:
        """Select a permitted correction only while unaccepted, then return checked facts."""
        ...

    return app, events, received, lookups


@pytest.mark.parametrize(
    "values,status",
    [
        ([], 409),
        ([Candidate(action=str(i)) for i in range(129)], 409),
        ([Candidate(action="x" * 66000)], 409),
        ([{"action": 1}], 502),
    ],
)
def test_unavailable_or_invalid_domain_aborts_before_selection(values, status):
    app, events, received, lookups = application(values)
    response = TestClient(build_app(app), raise_server_exceptions=False).post(
        "/status", json={"key": "private-record"}
    )
    assert response.status_code == status
    assert "private-record" not in response.text and "xxxx" not in response.text
    assert events == ["probe", "candidates"] and received == [] and lookups == []


def test_singleton_binds_canonical_candidate_without_model_resolution():
    candidate = Candidate(action="trim")
    app, events, received, lookups = application([candidate])
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert result.accepted is True
    assert events == ["probe", "candidates", "apply", "probe", "persist"]
    assert len(received) == 1 and received[0].action == "trim" and lookups == []


def test_retry_preserves_domain_and_one_lookup():
    attempts = []

    def callback(messages, info):
        attempts.append(domain(messages))
        return choose(messages, info, invalid=len(attempts) == 1)

    app, events, received, lookups = application(
        [Candidate(action="trim"), Candidate(action="uppercase")], callback, retries=1
    )
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert result.accepted is True and len(received) == 1
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert events.count("candidates") == 1 and lookups == [1]


def test_retry_charges_shared_inference_budget_before_effect():
    attempts = []

    def callback(messages, info):
        attempts.append(1)
        return choose(messages, info, invalid=True)

    app, events, received, lookups = application(
        [Candidate(action="trim"), Candidate(action="uppercase")],
        callback,
        retries=1,
        limits=UsageLimits(request_limit=1),
    )
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert attempts == [1] and received == [] and lookups == [1]
    assert events == ["probe", "candidates"]


def test_cross_request_token_cannot_authorize_another_request():
    previous = []

    def callback(messages, info):
        current = domain(messages)
        slot, data = next(iter(current.items()))
        if not previous:
            previous.append(data["candidates"][0]["token"])
            return choose(messages, info)
        assert previous[0] not in {c["token"] for c in data["candidates"]}
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {slot: previous[0]})]
        )

    app, _, _, _ = application(
        [Candidate(action="trim"), Candidate(action="uppercase")], callback
    )
    assert asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"})).accepted
    second, events, received, _ = application(
        [Candidate(action="trim"), Candidate(action="uppercase")], callback
    )
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(second._runtime.call(second.endpoints[0], {"key": "B"}))
    assert events == ["probe", "candidates"] and received == []


def test_injected_arguments_cannot_start_continuation():
    app, events, received, _ = application(
        [Candidate(action="trim"), Candidate(action="uppercase")],
        lambda messages, info: choose(messages, info, extra=True),
    )
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert events == ["probe", "candidates"] and received == []
