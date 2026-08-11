"""Tests for the HTTP server — verifies FastAPI routes are built from endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from summonpot import Pot, __version__
from summonpot.server import build_app


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
