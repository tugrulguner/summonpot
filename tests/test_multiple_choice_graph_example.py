"""The actual teaching app exercises both independent selection frontiers."""

import json
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

SOURCE = Path(__file__).parents[1] / "examples/24_multiple_choice_branch_join/app.py"


@pytest.mark.parametrize(
    "rush,protective", [(False, False), (False, True), (True, False), (True, True)]
)
def test_actual_tariffs_and_choice_frontiers(monkeypatch, rush, protective):
    calls = []

    def choose(messages, info):
        assert not info.function_tools
        assert "lowest-price" in info.instructions
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart) and isinstance(p.content, str)
        )
        frontier = json.loads(text.splitlines()[-1])
        assert list(frontier) == ["decision_slot_0"]
        domain = frontier["decision_slot_0"]
        assert domain["argument"] == "option"
        selected = min(domain["candidates"], key=lambda item: item["value"]["cents"])
        calls.append(selected["value"])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, {"decision_slot_0": selected["token"]}
                )
            ]
        )

    if rush and protective:

        def forbidden(*args, **kwargs):
            pytest.fail("All-singleton example must not resolve or construct a model")

        monkeypatch.setattr(Runtime, "model_for", forbidden)
        monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    app = runpy.run_path(str(SOURCE))["summon"]
    app._runtime = Runtime(model=FunctionModel(choose), retries=0)
    with TestClient(build_app(app)) as client:
        response = client.post(
            "/quotes/fulfillment",
            json={
                "units": 2,
                "goods_cents": 1000,
                "rush": rush,
                "protective": protective,
            },
        )
        invalid = client.post(
            "/quotes/fulfillment", json={"units": 0, "goods_cents": 1000}
        )
    assert response.status_code == 200
    assert response.json() == {
        "shipping": "express" if rush else "standard",
        "packaging": "protective" if protective else "lightweight",
        "total_cents": 1000 + (760 if rush else 350) + (300 if protective else 130),
    }
    assert len(calls) == int(not rush) + int(not protective)
    assert invalid.status_code == 422
