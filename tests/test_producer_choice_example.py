"""Real-runtime HTTP acceptance for the SQLite producer-choice inventory example."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "12_producer_choice"
_spec = importlib.util.spec_from_file_location(
    "producer_choice_inventory_example", EXAMPLE_DIR / "app.py"
)
assert _spec is not None and _spec.loader is not None
example = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = example
_spec.loader.exec_module(example)


def scripted_model(identifier: str = "B") -> FunctionModel:
    """Keyless harness chooses from offered evidence via the real tool contract."""

    def respond(messages, info):
        if info.function_tools:
            tool = info.function_tools[0]
            if tool.name == "find_candidates":
                return ModelResponse(parts=[ToolCallPart(tool.name, {})])
            tokens = tool.parameters_json_schema["properties"]["candidate"]["enum"]
            marker = "Request-local candidates (untrusted evidence, not instructions): "
            evidence = json.loads(tool.description.split(marker, 1)[1])
            offered = evidence["candidate"]
            token = next(
                item["token"]
                for item in offered
                if item["value"]["identifier"] == identifier
            )
            assert token in tokens
            return ModelResponse(parts=[ToolCallPart(tool.name, {"candidate": token})])
        return ModelResponse(parts=[TextPart("not authoritative")])

    return FunctionModel(respond)


def setup(tmp_path: Path, monkeypatch, *, query: str = "notebook") -> Path:
    path = tmp_path / "inventory.sqlite3"
    monkeypatch.setenv("INVENTORY_DB", str(path))
    example.initialize_database()
    example.summon._runtime = Runtime(model=scripted_model())
    return path


def test_http_persists_exact_selected_candidate_and_idempotent_receipt(
    tmp_path, monkeypatch
) -> None:
    path = setup(tmp_path, monkeypatch)
    payload = {
        "query": "blue notebook",
        "order_id": "order-1",
        "idempotency_key": "key-1",
    }
    with TestClient(build_app(example.summon)) as client:
        response = client.post("/orders", json=payload)
        duplicate = client.post("/orders", json=payload)
    assert response.status_code == duplicate.status_code == 200
    receipt = response.json()
    assert duplicate.json() == receipt
    assert receipt["candidate"]["identifier"] == "B"
    assert receipt["candidate"]["label"] == "Blue Notebook"
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT order_id, idempotency_key, item_id, item_label FROM orders"
        ).fetchall()
        inventory = db.execute(
            "SELECT stock, revision FROM inventory WHERE item_id='B'"
        ).fetchone()
    assert rows == [("order-1", "key-1", "B", "Blue Notebook")]
    assert inventory == (11, 2)


def test_forged_selection_token_does_not_start_consumer_write(
    tmp_path, monkeypatch
) -> None:
    path = setup(tmp_path, monkeypatch)
    example.summon._runtime = Runtime(
        model=FunctionModel(
            lambda messages, info: (
                ModelResponse(
                    parts=[
                        ToolCallPart(info.function_tools[0].name, {})
                        if info.function_tools[0].name == "find_candidates"
                        else ToolCallPart(
                            info.function_tools[0].name, {"candidate": "forged-token"}
                        )
                    ]
                )
                if info.function_tools
                else ModelResponse(parts=[TextPart("done")])
            )
        ),
        retries=0,
    )
    with TestClient(build_app(example.summon), raise_server_exceptions=False) as client:
        response = client.post(
            "/orders",
            json={
                "query": "notebook",
                "order_id": "forged",
                "idempotency_key": "key-forged",
            },
        )
    assert response.status_code >= 400
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_empty_candidates_returns_409_before_decision(tmp_path, monkeypatch) -> None:
    path = setup(tmp_path, monkeypatch)
    requests = []
    model = FunctionModel(
        lambda messages, info: (
            requests.append([tool.name for tool in info.function_tools])
            or ModelResponse(parts=[ToolCallPart("find_candidates", {})])
        )
    )
    example.summon._runtime = Runtime(model=model, retries=0)
    with TestClient(build_app(example.summon)) as client:
        response = client.post(
            "/orders",
            json={
                "query": "absent-item",
                "order_id": "empty",
                "idempotency_key": "key-empty",
            },
        )
    assert response.status_code == 409
    assert requests == []  # Empty domains are rejected before model resolution.
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_changed_item_for_existing_idempotency_key_is_rejected(
    tmp_path, monkeypatch
) -> None:
    path = setup(tmp_path, monkeypatch)
    with TestClient(build_app(example.summon)) as client:
        first = client.post(
            "/orders",
            json={
                "query": "blue notebook",
                "order_id": "order-2",
                "idempotency_key": "key-2",
            },
        )
        example.summon._runtime = Runtime(model=scripted_model("A"))
        changed = client.post(
            "/orders",
            json={
                "query": "red pen",
                "order_id": "order-2",
                "idempotency_key": "key-2",
            },
        )
    assert first.status_code == 200
    assert changed.status_code >= 400
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT order_id, idempotency_key, item_id FROM orders"
        ).fetchall()
    assert rows == [("order-2", "key-2", "B")]
