"""Multiple resolved prefix/suffix steps do not impose an arbitrary chain cap."""

import asyncio
from typing import Literal

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_stage_chains import Prepared, Report, Request, Snapshot, Verified

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


def test_two_prefixes_and_four_suffixes_share_one_closed_stage():
    events = []

    def prepare(key: str) -> Prepared:
        events.append("prepare")
        return Prepared(key=key)

    def prepare_more(key: str) -> Prepared:
        events.append("prepare_more")
        return Prepared(key=key + "-ready")

    def inspect(key: str, check: Literal["stock"]) -> Snapshot:
        events.append("inspect")
        return Snapshot(key=key, check=check)

    def suffix(name):
        def transform(key: str, check: str) -> Verified:
            events.append(name)
            return Verified(key=key, check=check)

        transform.__name__ = name
        return transform

    def finish(key: str, check: str) -> Report:
        events.append("finish")
        return Report(key=key, check=check)

    p1 = Operation(prepare, bind={"key": FromRequest("key")}, output=Prepared)
    p2 = Operation(prepare_more, bind={"key": FromResult(p1, "key")}, output=Prepared)
    repeated = Operation(
        inspect,
        bind={"key": FromResult(p2, "key"), "check": AgentChoice()},
        output=Snapshot,
    )
    s1 = Operation(
        suffix("verify_one"),
        bind={
            "key": FromResult(repeated, "key", invocation="final"),
            "check": FromResult(repeated, "check", invocation="final"),
        },
        output=Verified,
    )
    s2 = Operation(
        suffix("verify_two"),
        bind={"key": FromResult(s1, "key"), "check": FromResult(s1, "check")},
        output=Verified,
    )
    s3 = Operation(
        suffix("verify_three"),
        bind={
            "key": FromResult(s2, "key"),
            "check": FromResult(repeated, "check", invocation="final"),
        },
        output=Verified,
    )
    last = Operation(
        finish,
        bind={"key": FromResult(s3, "key"), "check": FromResult(s3, "check")},
        output=Report,
    )
    decisions = iter(
        [{"decision": "invoke", "argument_0": "stock"}, {"decision": "finish"}]
    )

    def choose(messages, info):
        assert not info.function_tools
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(decisions))]
        )

    app = Summon("long-stage-chain", runtime=Runtime(model=FunctionModel(choose)))

    @app("/review")
    def endpoint(
        request: Request,
        p=Required(p1, calls=Exactly(1)),
        pmore=Required(p2, calls=Exactly(1)),
        work=Required(repeated, calls=Between(1, 3)),
        a=Required(s1, calls=Exactly(1)),
        b=Required(s2, calls=Exactly(1)),
        c=Required(s3, calls=Exactly(1)),
        report=Required(last, calls=Exactly(1)),
    ) -> Report:
        """Prepare, inspect within bounds, verify in sequence and return the final report."""
        ...

    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "long"}))
    assert result == Report(key="long-ready", check="stock")
    assert events == [
        "prepare",
        "prepare_more",
        "inspect",
        "verify_one",
        "verify_two",
        "verify_three",
        "finish",
    ]
