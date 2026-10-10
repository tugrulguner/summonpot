"""End-to-end regression tests for endpoint annotation ownership."""

import asyncio
from typing import Annotated

import pytest
from fastapi.testclient import TestClient
from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import _registered_plan
from summonpot.runtime import Runtime, _OperationOutputError
from summonpot.server import build_app


class Request(BaseModel):
    value: int


class Response(BaseModel):
    value: int


def declare(summon, request_type, response_type, operation=None):
    if operation is None:

        def endpoint(request):
            """Return the validated value."""
            ...
    else:

        def bound_endpoint(request, result=Required(operation, calls=Exactly(1))):
            """Return the validated value using the exact operation."""
            ...

        endpoint = bound_endpoint

    endpoint.__annotations__ = {"request": request_type, "return": response_type}
    summon("/value")(endpoint)
    return summon.endpoints[0]


def model_for(value):
    def generate(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"value": value})]
        )

    return FunctionModel(generate)


def test_request_metadata_reaches_http_schema_and_validation():
    def positive(value):
        if value.value < 0:
            raise ValueError("negative request")
        return value

    request_type = Annotated[
        Request, AfterValidator(positive), Field(description="request metadata")
    ]
    summon = Summon(runtime=Runtime(model=model_for(7)))
    declare(summon, request_type, Response)
    client = TestClient(build_app(summon))
    schema = client.get("/openapi.json").json()["paths"]["/value"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert schema["description"] == "request metadata"
    assert client.post("/value", json={"value": -1}).status_code == 422
    assert client.post("/value", json={"value": 7}).json() == {"value": 7}
    assert client.post("/value", json={"request": {"value": 7}}).status_code == 422


def test_request_metadata_preserved_on_direct_raw_and_http_paths():
    received = []

    def before(value):
        return {"value": int(value["value"]) + 1}

    def after(value):
        if value.value < 0:
            raise ValueError("negative request")
        return value

    def echo(value: int) -> Response:
        received.append(value)
        return Response(value=value)

    request_type = Annotated[Request, BeforeValidator(before), AfterValidator(after)]
    op = Operation(echo, bind={"value": FromRequest("value")}, output=Response)
    summon = Summon(model="invalid-provider:no-model")
    endpoint = declare(summon, request_type, Response, op)
    plan = _registered_plan(endpoint)
    assert plan is not None and plan.direct_tool == 0
    assert asyncio.run(summon._runtime.call(endpoint, {"value": "4"})).value == 5
    client = TestClient(build_app(summon))
    assert client.post("/value", json={"value": "8"}).json() == {"value": 9}
    assert received == [5, 9]
    with pytest.raises(ValidationError):
        asyncio.run(summon._runtime.call(endpoint, {"value": -3}))
    assert client.post("/value", json={"value": -3}).status_code == 422
    assert received == [5, 9]


def test_response_metadata_enforced_by_agent_runtime():
    def positive(value):
        if value.value < 0:
            raise ValueError("negative output")
        return value

    response_type = Annotated[Response, AfterValidator(positive)]
    summon = Summon(runtime=Runtime(model=model_for(-1), retries=0))
    endpoint = declare(summon, Request, response_type)
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(summon._runtime.call(endpoint, {"value": 1}))
    assert (
        TestClient(build_app(summon)).post("/value", json={"value": 1}).status_code
        == 502
    )


def test_annotated_response_requires_exact_operation_output_for_direct_path():
    def positive(value):
        if value.value < 0:
            raise ValueError("negative output")
        return value

    def echo(value: int) -> Response:
        return Response(value=value)

    response_type = Annotated[Response, AfterValidator(positive)]
    bare_op = Operation(echo, bind={"value": FromRequest("value")}, output=Response)
    mismatch = declare(Summon(model="test"), Request, response_type, bare_op)
    plan = _registered_plan(mismatch)
    assert plan is not None and plan.direct_tool is None
    exact_op = Operation(
        echo, bind={"value": FromRequest("value")}, output=response_type
    )
    summon = Summon(model="invalid-provider:no-model")
    endpoint = declare(summon, Request, response_type, exact_op)
    plan = _registered_plan(endpoint)
    assert plan is not None and plan.direct_tool == 0
    assert asyncio.run(summon._runtime.call(endpoint, {"value": 2})).value == 2
    with pytest.raises(_OperationOutputError):
        asyncio.run(summon._runtime.call(endpoint, {"value": -1}))


@pytest.mark.parametrize("name", ["self", "cls"])
@pytest.mark.parametrize("transport", ["body", "query", "path"])
def test_business_receiver_names_reach_http_runtime(name, transport):
    seen = []

    def generate(messages, info):
        seen.extend(str(message) for message in messages)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"value": 42})]
        )

    summon = Summon(runtime=Runtime(model=FunctionModel(generate)))
    namespace = {"Response": Response}
    exec(
        f"def endpoint({name}: int) -> Response:\n    '''Use the business value.'''\n    ...\n",
        namespace,
    )
    route = "/value/{" + name + "}" if transport == "path" else "/value"
    method = "GET" if transport == "query" else "POST"
    summon(route, method=method)(namespace["endpoint"])
    client = TestClient(build_app(summon))
    if transport == "body":
        response = client.post(route, json={name: 37})
    elif transport == "query":
        response = client.get(route, params={name: 37})
    else:
        response = client.post("/value/37")
    assert response.status_code == 200
    assert any(f"{name}: 37" in message for message in seen)
    schema = client.get("/openapi.json").json()["paths"][route][method.lower()]
    if transport != "body":
        assert any(parameter["name"] == name for parameter in schema["parameters"])


def test_unbound_endpoint_receiver_is_rejected_without_name_heuristic():
    class Service:
        def endpoint(receiver, value: int) -> Response:  # pyright: ignore[reportSelfClsParameterName]
            """Return the business value."""
            ...

    with pytest.raises(TypeError, match="unbound method"):
        Summon()("/value")(Service.endpoint)
