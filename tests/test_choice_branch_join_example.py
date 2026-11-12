"""The new lesson teaches a real choice graph, not fixture-owned orchestration."""

import json
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

SOURCE = (
    Path(__file__).resolve().parent.parent / "examples/23_choice_branch_join/app.py"
)
PAYLOAD = {"quantity": 2, "unit_price_cents": 150, "unit_weight_grams": 700}


def test_business_tariffs_and_request_owned_filter():
    namespace = runpy.run_path(str(SOURCE))
    offers = namespace["list_shipping"](2, 700, 4)
    assert [(x.service, x.cents, x.delivery_days) for x in offers] == [
        ("standard", 700, 4),
        ("express", 1350, 1),
    ]
    assert [x.service for x in namespace["list_shipping"](2, 700, 1)] == ["express"]


def test_singleton_graph_serves_without_a_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Singleton quote must not use a model")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    app = runpy.run_path(str(SOURCE))["summon"]
    with TestClient(build_app(app)) as client:
        result = client.post(
            "/quotes/shipping-choice", json={**PAYLOAD, "max_delivery_days": 1}
        )
    assert result.status_code == 200
    assert result.json() == {
        "merchandise_cents": 300,
        "shipping_cents": 1350,
        "service": "express",
        "total_cents": 1650,
    }


def test_ambiguous_graph_uses_only_canonical_evidence_then_singleton_bypasses_model():
    calls = []

    def choose(messages, info):
        assert not info.function_tools
        assert "lowest-price" in info.instructions
        text = next(
            part.content
            for message in reversed(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        domains = json.loads(text.splitlines()[-1])
        assert list(domains) == ["decision_slot_0"]
        domain = domains["decision_slot_0"]
        assert domain["argument"] == "offer"
        selected = min(domain["candidates"], key=lambda item: item["value"]["cents"])
        calls.append(selected["value"])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "decision_slot_0": selected["token"],
                    },
                )
            ]
        )

    app = runpy.run_path(str(SOURCE))["summon"]
    app._runtime = Runtime(model=FunctionModel(choose), retries=0)
    with TestClient(build_app(app)) as client:
        result = client.post(
            "/quotes/shipping-choice", json={**PAYLOAD, "max_delivery_days": 4}
        )
        singleton = client.post(
            "/quotes/shipping-choice", json={**PAYLOAD, "max_delivery_days": 1}
        )
    assert result.status_code == singleton.status_code == 200
    assert result.json() == {
        "merchandise_cents": 300,
        "shipping_cents": 700,
        "service": "standard",
        "total_cents": 1000,
    }
    assert singleton.json()["total_cents"] == 1650
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes", [{"quantity": 0}, {"max_delivery_days": 0}, {"max_delivery_days": 5}]
)
def test_invalid_business_inputs_reject_before_selection(monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid request resolved a model")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    app = runpy.run_path(str(SOURCE))["summon"]
    with TestClient(build_app(app)) as client:
        result = client.post("/quotes/shipping-choice", json={**PAYLOAD, **changes})
    assert result.status_code == 422
