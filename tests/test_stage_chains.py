"""One repeated stage composed with resolved prefix/suffix operations."""

import asyncio
from typing import Literal

from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import (
    AgentChoice,
    Between,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime


class Request(BaseModel):
    key: str


class Prepared(BaseModel):
    key: str


class Snapshot(BaseModel):
    key: str
    check: str


class Verified(BaseModel):
    key: str
    check: str


class Report(BaseModel):
    key: str
    check: str


def chain_app(*, reverse=False, decisions=None, runtime_options=None):
    events = []
    turns = []
    replies = iter(
        decisions
        or [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "invoke", "argument_0": "prices"},
            {"decision": "finish"},
        ]
    )

    def prepare(key: str) -> Prepared:
        events.append(("prepare", key))
        return Prepared(key="prepared-" + key)

    def inspect(key: str, check: Literal["stock", "prices"]) -> Snapshot:
        events.append(("inspect", key, check))
        return Snapshot(key=key, check=check)

    def verify(key: str, check: str) -> Verified:
        events.append(("verify", key, check))
        return Verified(key=key, check=check)

    def finalize(key: str, check: str) -> Report:
        events.append(("finalize", key, check))
        return Report(key=key, check=check)

    def choose(messages, info):
        assert not info.function_tools
        assert all(e[0] not in ("verify", "finalize") for e in events)
        turns.append(1)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(replies))]
        )

    class ObservedRuntime(Runtime):
        def model_for(self, endpoint):
            events.append(("model-resolution",))
            return super().model_for(endpoint)

    runtime = ObservedRuntime(
        model=FunctionModel(choose), retries=0, **(runtime_options or {})
    )
    prepared = Operation(prepare, bind={"key": FromRequest("key")}, output=Prepared)
    repeated = Operation(
        inspect,
        bind={"key": FromResult(prepared, "key"), "check": AgentChoice()},
        output=Snapshot,
    )
    verified = Operation(
        verify,
        bind={
            "key": FromResult(repeated, "key", invocation="final"),
            "check": FromResult(repeated, "check", invocation="final"),
        },
        output=Verified,
    )
    terminal = Operation(
        finalize,
        bind={
            "key": FromResult(verified, "key"),
            "check": FromResult(verified, "check"),
        },
        output=Report,
    )
    app = Summon("stage-chain", runtime=runtime)
    p, w, v, r = (
        Required(prepared, calls=Exactly(1)),
        Required(repeated, calls=Between(1, 3)),
        Required(verified, calls=Exactly(1)),
        Required(terminal, calls=Exactly(1)),
    )
    if reverse:

        @app("/review")
        def reversed_endpoint(
            request: Request, result=r, verification=v, work=w, preparation=p
        ) -> Report:
            """Prepare, inspect within bounds, verify, and return the final report."""
            ...
    else:

        @app("/review")
        def endpoint(
            request: Request, preparation=p, work=w, verification=v, result=r
        ) -> Report:
            """Prepare, inspect within bounds, verify, and return the final report."""
            ...

    return app, runtime, events, turns


def test_prefix_stage_suffix_uses_one_run_and_only_stage_model_decisions():
    app, runtime, events, turns = chain_app()
    result = asyncio.run(runtime.call(app.endpoints[0], {"key": "a"}))
    assert result == Report(key="prepared-a", check="prices")
    assert events == [
        ("prepare", "a"),
        ("model-resolution",),
        ("inspect", "prepared-a", "stock"),
        ("inspect", "prepared-a", "prices"),
        ("verify", "prepared-a", "prices"),
        ("finalize", "prepared-a", "prices"),
    ]
    assert len(turns) == 3
