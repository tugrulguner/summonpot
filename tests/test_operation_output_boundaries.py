"""Output completion must not weaken explicit output or default/input authority."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    value: int
    factor: int = 99


class Response(BaseModel):
    value: int


@pytest.mark.parametrize("annotation", [str, "UnavailableReturnAnnotation"])
def test_explicit_output_wins_over_conflicting_or_unresolved_return(annotation):
    def calculate(value: int) -> Response:
        return Response(value=value)

    calculate.__annotations__["return"] = annotation
    operation = Operation(
        calculate, bind={"value": FromRequest("value")}, output=Response
    )
    app = Summon("explicit-output", runtime=Runtime(model="invalid:no-provider"))

    @app("/run")
    def endpoint(
        request: Request, result=Required(operation, calls=Exactly(1))
    ) -> Response:
        """Use the explicit output contract, not the callable's return hint."""
        ...

    assert asyncio.run(app._runtime.call(app.endpoints[0], {"value": 3})).value == 3
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"value": 4})
    assert response.status_code == 200 and response.json() == {"value": 4}
    assert operation.output is Response


@pytest.mark.parametrize("inferred", [False, True])
def test_output_completion_does_not_bind_same_named_request_field_to_default(inferred):
    starts = []

    def calculate(value: int, factor: int = 2) -> Response:
        starts.append((value, factor))
        return Response(value=value * factor)

    operation = (
        Operation(calculate, bind={"value": FromRequest("value")})
        if inferred
        else Operation(calculate, bind={"value": FromRequest("value")}, output=Response)
    )
    app = Summon("explicit-inputs", runtime=Runtime(model="invalid:no-provider"))

    @app("/run")
    def endpoint(
        request: Request, result=Required(operation, calls=Exactly(1))
    ) -> Response:
        """Retain the callable default rather than infer a new request binding."""
        ...

    body = {"value": 3, "factor": 99}
    assert asyncio.run(app._runtime.call(app.endpoints[0], body)).value == 6
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json=body)
    assert response.status_code == 200 and response.json() == {"value": 6}
    assert starts == [(3, 2), (3, 2)]
    assert operation.bind is not None and set(operation.bind) == {"value"}
    assert operation.output is (None if inferred else Response)


def test_nested_unresolved_return_is_rejected_before_admission_or_execution():
    starts = []

    def calculate(value: int):
        starts.append(value)
        return [Response(value=value)]

    calculate.__annotations__["return"] = list.__class_getitem__("MissingNestedReturn")
    operation = Operation(calculate, bind={"value": FromRequest("value")})
    app = Summon("invalid-nested-output")
    with pytest.raises(
        TypeError,
        match="Could not resolve the annotation 'MissingNestedReturn' for operation return type",
    ):

        @app("/run")
        def endpoint(
            request: Request, result=Required(operation, calls=Exactly(1))
        ) -> Response:
            """Reject the unavailable output contract before executing anything."""
            ...

    assert starts == [] and app.endpoints == [] and operation.output is None
