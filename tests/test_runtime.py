"""Tests for Pydantic structured output in the agent runtime."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from summonpot import Pot
from summonpot.runtime import Runtime


class ResearchRequest(BaseModel):
    query: str


class ResearchResponse(BaseModel):
    summary: str
    confidence: float


class FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


class FakeAsyncClient:
    response_data: dict[str, Any]
    requests: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return FakeResponse(self.response_data)


def test_runtime_requests_and_validates_pydantic_structured_output(monkeypatch):
    pot = Pot("svc")

    @pot.summon("/research")
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        raise NotImplementedError

    FakeAsyncClient.requests = []
    FakeAsyncClient.response_data = {
        "choices": [
            {
                "message": {
                    "content": '{"summary":"Pydantic contracts","confidence":0.95}'
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    runtime = Runtime()
    runtime.api_key = "test-key"
    result = asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))

    assert result == ResearchResponse(
        summary="Pydantic contracts",
        confidence=0.95,
    )
    body = FakeAsyncClient.requests[0]["json"]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "ResearchResponse",
            "schema": ResearchResponse.model_json_schema(),
        },
    }


def test_runtime_rejects_output_that_violates_response_model(monkeypatch):
    pot = Pot("svc")

    @pot.summon("/research")
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        raise NotImplementedError

    FakeAsyncClient.requests = []
    FakeAsyncClient.response_data = {
        "choices": [{"message": {"content": '{"summary":"Incomplete"}'}}]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    runtime = Runtime()
    runtime.api_key = "test-key"
    with pytest.raises(ValidationError, match="confidence"):
        asyncio.run(runtime.call(pot.endpoints[0], {"query": "agents"}))
