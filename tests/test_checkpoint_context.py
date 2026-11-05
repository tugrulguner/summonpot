"""Trusted context is admitted once and isolated throughout checkpoint rounds."""

import asyncio
import json
from typing import Annotated, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
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
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime, _ContextError
from summonpot.server import build_app


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant: str
    level: str = "allowed"
    private_marker: str


def contextual():
    counters = {}
    events = []
    prompts = []
    authentications = []

    def probe(key: str, tenant: str) -> CheckedStatus:
        value = counters.get((tenant, key), 0)
        events.append(("probe", tenant, value))
        return CheckedStatus(key=key, accepted=value >= 2, revision=value)

    def advance(
        key: str, tenant: str, private: str, pace: Literal["normal", "accelerated"]
    ) -> RefreshReceipt:
        assert private == f"private-{tenant}"
        assert pace == "normal"
        counters[(tenant, key)] = counters.get((tenant, key), 0) + 1
        events.append(("advance", tenant))
        return RefreshReceipt(revision=counters[(tenant, key)])

    def finish(
        key: str,
        accepted: bool,
        revision: int,
        tenant: str,
        level: Annotated[str, Field(min_length=3)],
    ) -> StatusReport:
        assert level == "allowed"
        assert counters[(tenant, key)] == revision
        events.append(("finish", tenant))
        return StatusReport(key=key, accepted=accepted, revision=revision)

    a = Operation(
        probe,
        bind={"key": FromRequest("key"), "tenant": FromContext("tenant")},
        output=CheckedStatus,
    )
    b = Operation(
        advance,
        bind={
            "key": FromResult(a, "key"),
            "tenant": FromContext("tenant"),
            "private": FromContext("private_marker"),
            "pace": AgentChoice(),
        },
        output=RefreshReceipt,
    )
    c = Operation(
        finish,
        bind={
            name: FromResult(a, name, invocation="final")
            for name in ("key", "accepted", "revision")
        }
        | {"tenant": FromContext("tenant"), "level": FromContext("level")},
        output=StatusReport,
    )

    async def respond(messages, info):
        assert not info.function_tools
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        assert isinstance(text, str)
        prompts.append(text)
        await asyncio.sleep(0)
        data = json.loads(text[text.index('{"decision_slot_') :])
        values = {
            slot: next(
                c["token"] for c in domain["candidates"] if c["value"] == "normal"
            )
            for slot, domain in data.items()
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, values)])

    def authenticate(request) -> Principal:
        authentications.append(1)
        return Principal(tenant="HTTP", private_marker="private-HTTP")

    runtime = Runtime(model=FunctionModel(respond), retries=0)
    app = Summon("context-checkpoint", runtime=runtime, context=authenticate)

    @app("/context-checkpoint")
    def endpoint(
        request: CheckpointRequest,
        check=Required(a, calls=Between(1, 3), until="accepted"),
        change=Depends(b, calls=AtMost(2)),
        report=Required(c, calls=Exactly(1)),
    ) -> StatusReport:
        """Advance each authenticated tenant with normal pace, then return its verified status."""
        ...

    return app, events, prompts, authentications


def test_concurrent_contexts_and_private_projection_are_isolated():
    app, events, prompts, auth = contextual()

    async def exercise():
        return await asyncio.gather(
            *(
                app._runtime.call(
                    app.endpoints[0],
                    {"key": "same"},
                    context=Principal(
                        tenant=tenant, private_marker=f"private-{tenant}"
                    ),
                )
                for tenant in ("A", "B")
            )
        )

    results = asyncio.run(exercise())
    assert all(result.accepted and result.revision == 2 for result in results)
    for tenant in ("A", "B"):
        assert (
            events.count(("advance", tenant)) == 2
            and events.count(("finish", tenant)) == 1
        )
    assert len(prompts) == 4 and not auth
    assert all("private-A" not in text and "private-B" not in text for text in prompts)


def test_suffix_only_receiving_context_is_preflighted_before_first_read():
    app, events, prompts, _ = contextual()
    with pytest.raises(_ContextError):
        asyncio.run(
            app._runtime.call(
                app.endpoints[0],
                {"key": "A"},
                context=Principal(tenant="A", level="x", private_marker="private-A"),
            )
        )
    assert events == [] and prompts == []


def test_http_explicit_quota_rejects_before_authentication_and_effects():
    app, events, prompts, auth = contextual()
    app._runtime.usage_limits = UsageLimits(tool_calls_limit=0)
    with TestClient(build_app(app)) as client:
        response = client.post("/context-checkpoint", json={"key": "A"})
    assert response.status_code == 500
    assert not auth and not events and not prompts


def test_replacement_call_cannot_bypass_http_context_admission():
    app, events, _, auth = contextual()

    class Bypass(Runtime):
        async def call(self, endpoint, params, *, context=None):
            return StatusReport(key="forged", accepted=True, revision=99)

    app._runtime = Bypass()
    with TestClient(build_app(app)) as client:
        response = client.post("/context-checkpoint", json={"key": "A"})
    assert response.status_code == 500
    assert not auth and not events
