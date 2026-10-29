"""Authenticated request-local authority survives multiple choice frontiers."""

import asyncio

import pytest
from pydantic import BaseModel, ConfigDict
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_multiple_choice_adversarial import Input, Item, Result

from summonpot import (
    AgentChoice,
    Exactly,
    FromContext,
    FromRequest,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: str


@pytest.mark.parametrize("ambiguous", [False, True])
def test_concurrent_context_is_preserved_and_never_implicitly_projected(ambiguous):
    starts, disclosures = [], []

    def authenticate(request) -> Principal:
        raise AssertionError("trusted Python context must not rerun authentication")

    def find(query: str, tenant_id: str) -> list[Item]:
        starts.append(("find", tenant_id, query))
        return [Item(key=query)] + ([Item(key=query + "-alt")] if ambiguous else [])

    a = Operation(
        find,
        bind={"query": FromRequest("query"), "tenant_id": FromContext("tenant_id")},
        output=list[Item],
    )

    def options(item: Item, tenant_id: str) -> list[Item]:
        starts.append(("options", tenant_id, item.key))
        return [Item(key=item.key + "-delivery")]

    b = Operation(
        options,
        bind={
            "item": AgentChoice(from_result=a),
            "tenant_id": FromContext("tenant_id"),
        },
        output=list[Item],
    )

    def finish(item: Item, tenant_id: str) -> Result:
        starts.append(("finish", tenant_id, item.key))
        return Result(key=tenant_id + ":" + item.key)

    c = Operation(
        finish,
        bind={
            "item": AgentChoice(from_result=b),
            "tenant_id": FromContext("tenant_id"),
        },
        output=Result,
    )
    app = Summon("context-frontiers", context=authenticate)

    @app("/context")
    def endpoint(
        request: Input,
        a=Required(a, calls=Exactly(1)),
        b=Required(b, calls=Exactly(1)),
        c=Required(c, calls=Exactly(1)),
    ) -> Result:
        """Choose a candidate and its delivery for the authenticated tenant."""
        ...

    def model(messages, info):
        disclosures.append(repr(messages) + repr(info.function_tools))
        if not info.function_tools:
            return ModelResponse(parts=[TextPart("not the receipt")])
        tool = info.function_tools[0]
        assert "tenant_id" not in tool.parameters_json_schema["properties"]
        token = tool.parameters_json_schema["properties"]["item"]["enum"][0]
        return ModelResponse(parts=[ToolCallPart(tool.name, {"item": token})])

    runtime = Runtime(model=FunctionModel(model))

    async def campaign():
        return await asyncio.gather(
            *(
                runtime.call(
                    app.endpoints[0],
                    {"query": str(i)},
                    context=Principal(tenant_id=f"private-tenant-{i}"),
                )
                for i in range(8)
            )
        )

    results = asyncio.run(campaign())
    assert {r.key for r in results} == {
        f"private-tenant-{i}:{i}-delivery" for i in range(8)
    }
    for i in range(8):
        tenant = f"private-tenant-{i}"
        assert [s for s in starts if s[1] == tenant] == [
            ("find", tenant, str(i)),
            ("options", tenant, str(i)),
            ("finish", tenant, f"{i}-delivery"),
        ]
        assert all(tenant not in disclosure for disclosure in disclosures)
    assert bool(disclosures) is ambiguous
