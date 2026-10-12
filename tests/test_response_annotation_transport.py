"""HTTP serialization must not repeat application output validation."""

import asyncio
from typing import Annotated

import pytest
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    WrapSerializer,
)
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    value: int


class Response(BaseModel):
    value: int = Field(serialization_alias="wireValue")


@pytest.mark.parametrize("path", ["direct", "agent"])
@pytest.mark.parametrize("kind", ["before", "after"])
@pytest.mark.parametrize("custom_serializer", [False, True])
def test_output_validation_once_with_raw_http_parity(path, kind, custom_serializer):
    validation_inputs = []
    serialization_inputs = []

    def transform(value):
        validation_inputs.append(type(value).__name__)
        if kind == "before":
            return {"value": int(value["value"]) + 1}
        return Response(value=value.value + 1)

    def serialize(value):
        serialization_inputs.append(value.value)
        return {"wireValue": value.value, "serialized": True}

    validator = (
        BeforeValidator(transform) if kind == "before" else AfterValidator(transform)
    )
    if custom_serializer:
        output = Annotated[
            Response,
            validator,
            PlainSerializer(serialize),
            Field(description="output metadata"),
        ]
    else:
        output = Annotated[Response, validator, Field(description="output metadata")]

    if path == "direct":

        def echo(value: int):
            return {"value": value}

        operation = Operation(echo, bind={"value": FromRequest("value")}, output=output)
        summon = Summon(model="invalid-provider:no-model")

        def endpoint(request, result=Required(operation, calls=Exactly(1))):
            """Return the value through the exact operation."""
            ...
    else:

        def generate(messages, info):
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"value": 4})]
            )

        summon = Summon(runtime=Runtime(model=FunctionModel(generate)))

        def agent_endpoint(request):
            """Return the value using bounded model output."""
            ...

        endpoint = agent_endpoint

    endpoint.__annotations__ = {"request": Request, "return": output}
    summon("/value")(endpoint)
    definition = summon.endpoints[0]
    raw = asyncio.run(summon._runtime.call(definition, {"value": 4}))
    assert raw.value == 5
    assert len(validation_inputs) == 1
    validation_inputs.clear()
    serialization_inputs.clear()

    client = TestClient(build_app(summon))
    response = client.post("/value", json={"value": 4})
    assert response.status_code == 200
    expected = {"wireValue": raw.value}
    if custom_serializer:
        expected["serialized"] = True
        assert serialization_inputs == [5]
    assert response.json() == expected
    assert len(validation_inputs) == 1
    schema = client.get("/openapi.json").json()["paths"]["/value"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert schema["description"] == "output metadata"


class Node(BaseModel):
    value: int = Field(serialization_alias="wireValue")
    children: list["Node"] = Field(default_factory=list)


@pytest.mark.parametrize("path", ["direct", "agent"])
def test_recursive_response_schema_and_wrap_serializer_survive(path):
    validations = []
    serializations = []

    def validate(value):
        validations.append(value.value)
        return Node(value=value.value + 1, children=value.children)

    def serialize(value, handler):
        serializations.append(value.value)
        result = handler(value)
        result["serialized"] = True
        return result

    output = Annotated[
        Node,
        AfterValidator(validate),
        WrapSerializer(serialize),
        Field(
            description="recursive response",
            examples=[{"wireValue": 5, "children": []}],
        ),
    ]
    payload = {"value": 4, "children": [{"value": 2}]}
    if path == "direct":

        def echo(value: int):
            return payload

        op = Operation(echo, bind={"value": FromRequest("value")}, output=output)
        summon = Summon(model="invalid-provider:no-model")

        def endpoint(request, result=Required(op, calls=Exactly(1))):
            """Return a recursive value through the exact operation."""
            ...
    else:

        def generate(messages, info):
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, payload)]
            )

        summon = Summon(runtime=Runtime(model=FunctionModel(generate)))

        def agent_endpoint(request):
            """Return a recursive value using bounded model output."""
            ...

        endpoint = agent_endpoint

    endpoint.__annotations__ = {"request": Request, "return": output}
    summon("/tree")(endpoint)
    definition = summon.endpoints[0]
    # Mutation of inspection metadata must not affect the registered transport.
    definition.output_annotation = Response
    client = TestClient(build_app(summon))
    response = client.post("/tree", json={"value": 4})
    assert response.status_code == 200
    assert response.json() == {
        "wireValue": 5,
        "children": [{"wireValue": 2, "children": []}],
        "serialized": True,
    }
    assert validations == [4]
    assert serializations == [5]
    schema = client.get("/openapi.json").json()
    output_schema = schema["paths"]["/tree"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert output_schema["description"] == "recursive response"
    assert output_schema["examples"] == [{"wireValue": 5, "children": []}]
    assert schema["components"]["schemas"]["Node"]["properties"]["children"]["items"][
        "$ref"
    ].endswith("/Node")
