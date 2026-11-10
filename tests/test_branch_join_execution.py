"""Resolved branches join through existing declarations, without model scheduling."""

import asyncio

from fastapi.testclient import TestClient
from pydantic import BaseModel

from summonpot import Exactly, FromRequest, FromResult, Operation, Required, Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    value: int


class BranchResult(BaseModel):
    value: int


class Response(BaseModel):
    total: int


def test_two_independent_branches_join_without_a_model():
    starts = []

    def left(value: int) -> BranchResult:
        starts.append("left")
        return BranchResult(value=value + 1)

    def right(value: int) -> BranchResult:
        starts.append("right")
        return BranchResult(value=value * 2)

    def finish(left_value: int, right_value: int) -> Response:
        starts.append("finish")
        return Response(total=left_value + right_value)

    first = Operation(left, bind={"value": FromRequest("value")})
    second = Operation(right, bind={"value": FromRequest("value")})
    terminal = Operation(
        finish,
        bind={
            "left_value": FromResult(first, "value"),
            "right_value": FromResult(second, "value"),
        },
    )
    app = Summon("branch-join", runtime=Runtime(model="invalid:no-provider"))

    @app("/combine")
    def combine(
        request: Request,
        result=Required(terminal, calls=Exactly(1)),
        one=Required(first, calls=Exactly(1)),
        two=Required(second, calls=Exactly(1)),
    ) -> Response:
        """Run both exact calculations, then return their combined result."""
        ...

    result = asyncio.run(app._runtime.call(app.endpoints[0], {"value": 3}))
    assert result == Response(total=10)
    assert starts == ["left", "right", "finish"]
    starts.clear()
    with TestClient(build_app(app)) as client:
        response = client.post("/combine", json={"value": 4})
    assert response.status_code == 200 and response.json() == {"total": 13}
    assert starts == ["left", "right", "finish"]
    assert first.output is None and second.output is None and terminal.output is None
