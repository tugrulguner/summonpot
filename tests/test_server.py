"""Tests for the HTTP server — verifies FastAPI routes are built from endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from summonpot import Pot, __version__
from summonpot.server import build_app


class AnalysisRequest(BaseModel):
    text: str = Field(min_length=3)
    max_topics: int = Field(default=3, ge=1, le=10, alias="maxTopics")


class AnalysisResponse(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]
    topics: list[str]


def test_build_app_creates_route(mock_runtime):
    pot = mock_runtime(mock_response="Hello, world!")

    @pot.summon("/hello")
    def hello(name: str) -> str:
        """Greet someone."""
        return ""

    app = build_app(pot)
    client = TestClient(app)
    response = client.post("/hello", json={"name": "world"})
    assert response.status_code == 200
    assert response.json() == "Hello, world!"


def test_build_app_uses_pydantic_request_and_response_models(mock_runtime):
    pot = mock_runtime(
        mock_response={"sentiment": "positive", "topics": ["agents", "apis"]}
    )

    @pot.summon("/analyze")
    def analyze(request: AnalysisRequest) -> AnalysisResponse:
        """Analyze text."""
        raise NotImplementedError

    client = TestClient(build_app(pot))
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/analyze"]["post"]

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert request_schema == {"$ref": "#/components/schemas/AnalysisRequest"}
    assert response_schema == {"$ref": "#/components/schemas/AnalysisResponse"}

    valid = client.post("/analyze", json={"text": "Great framework"})
    assert valid.status_code == 200
    assert valid.json() == {"sentiment": "positive", "topics": ["agents", "apis"]}
    pot._runtime.call.assert_awaited_once_with(
        pot.endpoints[0], {"text": "Great framework", "maxTopics": 3}
    )

    invalid = client.post("/analyze", json={"text": "x"})
    assert invalid.status_code == 422


def test_build_app_requires_body_fields(mock_runtime):
    pot = mock_runtime()

    @pot.summon("/strict")
    def strict(required_field: int) -> str:
        """Strict endpoint."""
        return ""

    app = build_app(pot)
    client = TestClient(app)
    # Missing required field → 422 validation error
    response = client.post("/strict", json={})
    assert response.status_code == 422


def test_build_app_openapi_has_endpoints():
    pot = Pot("svc")

    @pot.summon("/analyze")
    def analyze(text: str) -> dict:
        """Analyze text."""
        return {}

    app = build_app(pot)
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    operation = paths["/analyze"]["post"]
    assert schema["info"]["version"] == __version__
    assert operation.get("parameters", []) == []
    assert operation["requestBody"]["required"] is True
    assert "/analyze" in paths
    assert "post" in paths["/analyze"]


def test_build_app_no_body_route_hides_internal_context(mock_runtime):
    pot = mock_runtime(mock_response="ready")

    @pot.summon("/health")
    def health() -> str:
        """Report readiness."""
        return ""

    client = TestClient(build_app(pot))
    operation = client.get("/openapi.json").json()["paths"]["/health"]["post"]

    assert operation.get("parameters", []) == []
    assert "requestBody" not in operation
    response = client.post("/health")
    assert response.status_code == 200
    assert response.json() == "ready"
