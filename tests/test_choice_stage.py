"""Selection and repetition compose in one guarded endpoint run."""

import asyncio
import json
from typing import Literal

import pytest
from pydantic import BaseModel
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

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
    category: str


class Candidate(BaseModel):
    identifier: str


class Selected(BaseModel):
    identifier: str


class Snapshot(BaseModel):
    identifier: str
    check: str


class Report(BaseModel):
    identifier: str
    check: str


def application(count=2, *, runtime_options=None, selected_index=1, maximum=3):
    events = []
    turns = []
    resolved = []
    canonical = []

    def find(category: str) -> list[Candidate]:
        events.append("find")
        return [Candidate(identifier=f"{category}-{i}") for i in range(count)]

    def select(candidate: Candidate) -> Selected:
        events.append(("select", candidate.identifier))
        canonical.append(candidate)
        return Selected(identifier=candidate.identifier)

    def inspect(identifier: str, check: Literal["stock", "prices"]) -> Snapshot:
        events.append(("inspect", identifier, check))
        return Snapshot(identifier=identifier, check=check)

    def finish(identifier: str, check: str) -> Report:
        events.append(("finish", identifier, check))
        return Report(identifier=identifier, check=check)

    producer = Operation(
        find, bind={"category": FromRequest("category")}, output=list[Candidate]
    )
    selected = Operation(
        select, bind={"candidate": AgentChoice(from_result=producer)}, output=Selected
    )
    repeated = Operation(
        inspect,
        bind={"identifier": FromResult(selected, "identifier"), "check": AgentChoice()},
        output=Snapshot,
    )
    terminal = Operation(
        finish,
        bind={
            "identifier": FromResult(repeated, "identifier", invocation="final"),
            "check": FromResult(repeated, "check", invocation="final"),
        },
        output=Report,
    )

    def model(messages, info):
        assert not info.function_tools
        props = info.output_tools[0].parameters_json_schema["properties"]
        if "decision" in props:
            ordinal = sum(t == "check" for t in turns)
            turns.append("check")
            args = (
                {"decision": "invoke", "argument_0": ("stock", "prices")[ordinal]}
                if ordinal < 2
                else {"decision": "finish"}
            )
        else:
            turns.append("selection")
            prompt = next(
                p.content
                for m in messages
                for p in m.parts
                if isinstance(p, UserPromptPart)
            )
            assert isinstance(prompt, str)
            data = json.loads(prompt[prompt.index('{"decision_slot_') :])

            def candidates(value):
                if isinstance(value, dict):
                    if "candidates" in value:
                        return value["candidates"]
                    for child in value.values():
                        found = candidates(child)
                        if found is not None:
                            return found
                return None

            domain = candidates(data)
            assert domain is not None
            args = {next(iter(props)): domain[selected_index]["token"]}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    class Observed(Runtime):
        def model_for(self, endpoint):
            resolved.append(1)
            return super().model_for(endpoint)

    runtime = Observed(model=FunctionModel(model), retries=0, **(runtime_options or {}))
    app = Summon("choice-stage", runtime=runtime)

    @app("/review")
    def endpoint(
        request: Request,
        a=Required(producer, calls=Exactly(1)),
        b=Required(selected, calls=Exactly(1)),
        c=Required(repeated, calls=Between(1, maximum)),
        d=Required(terminal, calls=Exactly(1)),
    ) -> Report:
        """Select an eligible item, run both stock and prices checks, and return its report."""
        ...

    return app, events, turns, resolved, canonical


def test_singleton_candidate_skips_selection_but_runs_repeated_stage():
    app, events, turns, resolved, _ = application(count=1)
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"category": "supplier"}))
    assert result == Report(identifier="supplier-0", check="prices")
    assert events[0:2] == ["find", ("select", "supplier-0")]
    assert turns == ["check", "check", "check"]
    assert resolved == [1]


def test_empty_candidate_domain_stops_before_model_consumer_or_stage():
    app, events, turns, resolved, _ = application(count=0)
    with pytest.raises(RuntimeError, match="candidate domain"):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "supplier"}))
    assert events == ["find"]
    assert turns == []
    assert resolved == []


@pytest.mark.parametrize("count", [0, 129])
def test_empty_or_oversized_candidate_domain_stops_before_model_or_consumer(count):
    app, events, turns, resolved, _ = application(count=count)
    with pytest.raises(
        RuntimeError, match=r"candidate domain|exceeds its supported bound"
    ):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "supplier"}))
    assert events == ["find"]
    assert turns == []
    assert resolved == []


def test_shared_request_limit_covers_selection_and_repeated_decisions():
    app, events, turns, resolved, _ = application(
        runtime_options={"usage_limits": UsageLimits(request_limit=2)}
    )
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(app._runtime.call(app.endpoints[0], {"category": "supplier"}))
    assert events == [
        "find",
        ("select", "supplier-1"),
        ("inspect", "supplier-1", "stock"),
    ]
    assert turns == ["selection", "check"]
    assert resolved == [1]


def test_ambiguous_selection_precedes_repeated_stage_in_one_run():
    app, events, turns, resolved, _ = application()
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"category": "supplier"}))
    assert result == Report(identifier="supplier-1", check="prices")
    assert events == [
        "find",
        ("select", "supplier-1"),
        ("inspect", "supplier-1", "stock"),
        ("inspect", "supplier-1", "prices"),
        ("finish", "supplier-1", "prices"),
    ]
    assert turns == ["selection", "check", "check", "check"]
    assert resolved == [1]
