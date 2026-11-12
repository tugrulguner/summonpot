"""One permitted argument choice does not require artificial branch ordering."""

import asyncio

from pydantic import BaseModel

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime


class Request(BaseModel):
    value: int


class Value(BaseModel):
    value: int


class Candidate(BaseModel):
    value: int


class Response(BaseModel):
    total: int


def test_singleton_choice_branch_joins_without_model(monkeypatch):
    starts = []

    def forbidden(*args, **kwargs):
        raise AssertionError("A singleton choice graph must not resolve an agent")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    monkeypatch.setattr(Runtime, "_agent_for", forbidden)

    def left(value: int) -> Value:
        starts.append("left")
        return Value(value=value * 2)

    first = Operation(left, bind={"value": FromRequest("value")})

    def discover(value: int) -> list[Candidate]:
        starts.append("discover")
        return [Candidate(value=value + 3)]

    candidates = Operation(discover, bind={"value": FromRequest("value")})

    def select(candidate: Candidate) -> Value:
        starts.append("select")
        return Value(value=candidate.value)

    selected = Operation(
        select, bind={"candidate": AgentChoice(from_result=candidates)}
    )

    def finish(left_value: int, selected_value: int) -> Response:
        starts.append("finish")
        return Response(total=left_value + selected_value)

    terminal = Operation(
        finish,
        bind={
            "left_value": FromResult(first, "value"),
            "selected_value": FromResult(selected, "value"),
        },
    )
    app = Summon("choice-graph", runtime=Runtime(model="invalid:not-used"))

    @app("/combine")
    def endpoint(
        request: Request,
        result=Required(terminal, calls=Exactly(1)),
        one=Required(first, calls=Exactly(1)),
        two=Required(candidates, calls=Exactly(1)),
        three=Required(selected, calls=Exactly(1)),
    ) -> Response:
        """Run independent branches and return the exact joined result."""
        ...

    result = asyncio.run(app._runtime.call(app.endpoints[0], {"value": 5}))
    assert result == Response(total=18)
    assert starts == ["left", "discover", "select", "finish"]
