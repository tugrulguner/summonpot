"""Public HTTP coverage for the stateless transport lesson."""

import json
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

SOURCE = Path(__file__).resolve().parents[1] / "examples/21_path_methods/app.py"


def echo_model(messages, info):
    """Copy only validated values actually delivered to the SDK."""
    prompt = next(
        part.content
        for message in reversed(messages)
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )
    values = {}
    for line in prompt.splitlines():
        if line.startswith("  "):
            name, value = line.strip().split(": ", 1)
            values[name] = json.loads(value)
    assert type(values["item_id"]) is int
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, values)])


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@pytest.mark.parametrize("item_id", [7, 42])
def test_transport_uses_actual_sdk_request(method, item_id):
    summon = runpy.run_path(str(SOURCE))["summon"]
    observed = []

    def model(messages, info):
        result = echo_model(messages, info)
        observed.append(result.parts[0].args)
        return result

    summon._runtime = Runtime(model=FunctionModel(model))
    client = TestClient(build_app(summon))
    kwargs = {}
    expected = {"item_id": item_id}
    if method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {"text": "body evidence", "item_id": 999}
        expected["text"] = "body evidence"
    elif method == "GET":
        kwargs["params"] = {"text": "query evidence", "item_id": 999}
        expected["text"] = "query evidence"
    response = client.request(method, f"/transport/{item_id}", **kwargs)
    assert response.status_code == 200
    assert observed == [expected]
    if method == "HEAD":
        assert response.content == b""
    else:
        assert response.json() == expected
    assert client.request(method, "/transport/not-an-int", **kwargs).status_code == 422


def test_openapi_describes_path_body_and_query_ownership():
    schema = build_app(runpy.run_path(str(SOURCE))["summon"]).openapi()
    methods = schema["paths"]["/transport/{item_id}"]
    assert set(methods) == {"get", "post", "put", "patch", "delete", "head"}
    for method, route in methods.items():
        path = next(p for p in route["parameters"] if p["name"] == "item_id")
        assert path["in"] == "path"
        assert path["required"]
        assert path["schema"]["type"] == "integer"
        assert ("requestBody" in route) == (method in {"post", "put", "patch"})
        if "requestBody" in route:
            ref = route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            assert set(
                schema["components"]["schemas"][ref.rsplit("/", 1)[1]]["properties"]
            ) == {"text"}
    assert any(
        p["name"] == "text" and p["in"] == "query" for p in methods["get"]["parameters"]
    )


def test_release_wrapper_reads_sdk_values(tmp_path):
    smoke = runpy.run_path(str(SOURCE.parents[2] / "scripts/release_smoke.py"))
    wrapper = smoke["_path_methods_smoke_wrapper"](SOURCE, tmp_path)
    client = TestClient(build_app(runpy.run_path(str(wrapper))["summon"]))
    for item_id, text in [(13, "first"), (81, "second")]:
        response = client.post(
            f"/transport/{item_id}", json={"text": text, "item_id": 999}
        )
        assert response.status_code == 200
        assert response.json() == {"item_id": item_id, "text": text}
