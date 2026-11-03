"""Context and request isolation through selection and repetition."""

import asyncio
import json
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from test_choice_stage import Candidate, Report, Request, Selected, Snapshot

from summonpot import (
    AgentChoice,
    Between,
    Exactly,
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime, _ContextError


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant: str
    level: str = "allowed"
    private_marker: str


def contextual_app():
    events = []
    prompts = []

    def find(category: str, tenant: str) -> list[Candidate]:
        events.append(("find", tenant))
        return [Candidate(identifier=f"{tenant}/{category}/{i}") for i in range(2)]

    def select(candidate: Candidate, tenant: str) -> Selected:
        assert candidate.identifier.startswith(tenant + "/")
        events.append(("select", tenant, candidate.identifier))
        return Selected(identifier=candidate.identifier)

    def inspect(
        identifier: str, tenant: str, check: Literal["stock", "prices"]
    ) -> Snapshot:
        assert identifier.startswith(tenant + "/")
        events.append(("inspect", tenant, identifier))
        return Snapshot(identifier=identifier, check=check)

    def finish(
        identifier: str,
        check: str,
        tenant: str,
        level: Annotated[str, Field(min_length=3)],
    ) -> Report:
        assert identifier.startswith(tenant + "/")
        events.append(("finish", tenant, identifier))
        return Report(identifier=identifier, check=check)

    producer = Operation(
        find,
        bind={"category": FromRequest("category"), "tenant": FromContext("tenant")},
        output=list[Candidate],
    )
    chosen = Operation(
        select,
        bind={
            "candidate": AgentChoice(from_result=producer),
            "tenant": FromContext("tenant"),
        },
        output=Selected,
    )
    stage = Operation(
        inspect,
        bind={
            "identifier": FromResult(chosen, "identifier"),
            "tenant": FromContext("tenant"),
            "check": AgentChoice(),
        },
        output=Snapshot,
    )
    final = Operation(
        finish,
        bind={
            "identifier": FromResult(stage, "identifier", invocation="final"),
            "check": FromResult(stage, "check", invocation="final"),
            "tenant": FromContext("tenant"),
            "level": FromContext("level"),
        },
        output=Report,
    )

    def respond(messages, info):
        assert not info.function_tools
        prompt = next(
            p.content
            for m in messages
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        prompts.append(prompt)
        data = json.loads(prompt.splitlines()[-1])
        props = info.output_tools[0].parameters_json_schema["properties"]
        if "decision" in props:
            n = data["starts"]
            args = (
                {"decision": "invoke", "argument_0": ("stock", "prices")[n]}
                if n < 2
                else {"decision": "finish"}
            )
        else:
            slot = next(iter(props))
            args = {slot: data[slot]["candidates"][0]["token"]}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    def authenticate(request) -> Principal:
        raise AssertionError("Raw fixture supplies trusted context explicitly")

    app = Summon(
        "contextual-composition",
        runtime=Runtime(model=FunctionModel(respond), retries=0),
        context=authenticate,
    )

    @app("/review")
    def endpoint(
        request: Request,
        a=Required(producer, calls=Exactly(1)),
        b=Required(chosen, calls=Exactly(1)),
        c=Required(stage, calls=Between(1, 3)),
        d=Required(final, calls=Exactly(1)),
    ) -> Report:
        """Select a permitted item, check stock and prices, and return the tenant report."""
        ...

    return app, events, prompts


def test_concurrent_principals_keep_selection_and_closure_isolated():
    app, events, prompts = contextual_app()

    async def exercise():
        return await asyncio.gather(
            *[
                app._runtime.call(
                    app.endpoints[0],
                    {"category": "same"},
                    context=Principal(
                        tenant=tenant, private_marker="private-marker-" + tenant
                    ),
                )
                for tenant in ("tenant-a", "tenant-b")
            ]
        )

    output = asyncio.run(exercise())
    assert {r.identifier for r in output} == {"tenant-a/same/0", "tenant-b/same/0"}
    for tenant in ("tenant-a", "tenant-b"):
        own = [e for e in events if e[1] == tenant]
        assert [e[0] for e in own] == ["find", "select", "inspect", "inspect", "finish"]
        assert all(e[2] == tenant + "/same/0" for e in own[1:])
    # Candidate identifiers intentionally disclose their tenant; private context does not.
    assert all("private-marker-" not in prompt for prompt in prompts)


def test_suffix_context_constraint_preflights_before_candidate_query():
    app, events, prompts = contextual_app()
    with pytest.raises(_ContextError):
        asyncio.run(
            app._runtime.call(
                app.endpoints[0],
                {"category": "same"},
                context=Principal(
                    tenant="tenant-a", level="x", private_marker="unprojected"
                ),
            )
        )
    assert events == [] and prompts == []
