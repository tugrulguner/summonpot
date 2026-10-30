"""SQLite multiple-choice example: raw runtime and complete HTTP effects."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime


@pytest.fixture(autouse=True)
def isolate_database_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MULTIPLE_CHOICE_DB", str(tmp_path / "default.sqlite3"))


EXAMPLE = Path(__file__).parents[1] / "examples/13_multiple_producer_choices/app.py"


def load_app(tmp_path: Path, name: str = "multiple_choice_example"):
    import os

    os.environ["MULTIPLE_CHOICE_DB"] = str(tmp_path / f"{name}.sqlite3")
    spec = importlib.util.spec_from_file_location(name, EXAMPLE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_single_candidate_chain_runs_without_model_and_persists_idempotently(
    tmp_path, monkeypatch
):
    module = load_app(tmp_path, "single_choice_example")

    def forbidden(*args, **kwargs):
        raise AssertionError("singleton route must not resolve or construct a model")

    for method in ("model_for", "_agent_for", "_build_agent"):
        monkeypatch.setattr(Runtime, method, forbidden)

    with TestClient(
        __import__("summonpot.server", fromlist=["build_app"]).build_app(module.summon)
    ) as client:
        response = client.post(
            "/orders",
            json={"category": "stationery", "quantity": 1, "idempotency_key": "one"},
        )
    # stationery has no eligible products; this verifies a real empty producer domain.
    assert response.status_code == 409
    with sqlite3.connect(module.DB_PATH) as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 0

    # Coffee has one product and one compatible delivery, so the whole chain is local.
    with TestClient(
        __import__("summonpot.server", fromlist=["build_app"]).build_app(module.summon)
    ) as client:
        response = client.post(
            "/orders",
            json={"category": "coffee", "quantity": 1, "idempotency_key": "coffee-one"},
        )
    assert response.status_code == 200, response.text
    receipt = module.Receipt.model_validate(response.json())
    assert (receipt.product_id, receipt.delivery_id, receipt.total_cents) == (
        "coffee",
        "coffee-ground",
        350,
    )
    with TestClient(
        __import__("summonpot.server", fromlist=["build_app"]).build_app(module.summon)
    ) as client:
        replay = client.post(
            "/orders",
            json={"category": "coffee", "quantity": 1, "idempotency_key": "coffee-one"},
        )
    assert replay.status_code == 200 and replay.json() == receipt.model_dump()
    with sqlite3.connect(module.DB_PATH) as db:
        assert db.execute(
            "SELECT stock FROM products WHERE product_id='coffee'"
        ).fetchone() == (4,)
        assert db.execute(
            "SELECT count(*) FROM orders WHERE idempotency_key='coffee-one'"
        ).fetchone() == (1,)


def test_multi_candidate_full_http_selection_persists_receipt_and_stock(tmp_path):
    module = load_app(tmp_path, "multi_choice_example")
    calls = []

    def select_from_real_tool_schema(messages, info):
        import json

        from pydantic_ai.messages import ModelRequest, UserPromptPart

        assert info.function_tools == []
        assert len(info.output_tools) == 1
        tool = info.output_tools[0]
        calls.append(tool.parameters_json_schema)
        prompts = [
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        ]
        domains = json.loads(prompts[0].splitlines()[-1])
        assert "quantity" not in tool.parameters_json_schema["properties"]
        assert "idempotency_key" not in tool.parameters_json_schema["properties"]
        args = {slot: data["candidates"][0]["token"] for slot, data in domains.items()}
        return ModelResponse(parts=[ToolCallPart(tool.name, args)])

    module.summon._runtime = Runtime(model=FunctionModel(select_from_real_tool_schema))
    with TestClient(
        __import__("summonpot.server", fromlist=["build_app"]).build_app(module.summon)
    ) as client:
        response = client.post(
            "/orders",
            json={"category": "grocery", "quantity": 2, "idempotency_key": "tea-order"},
        )
        if response.status_code != 200:
            raise AssertionError(
                f"{response.status_code}: {response.text}; tools={calls!r}"
            )
        receipt = module.Receipt.model_validate(response.json())
        assert receipt.product_id in {"tea", "coffee"}
        assert receipt.delivery_id.startswith(receipt.product_id + "-")
        assert receipt.quantity == 2
        before = client.post(
            "/orders",
            json={"category": "grocery", "quantity": 2, "idempotency_key": "tea-order"},
        )
        assert before.status_code == 200 and before.json() == response.json()
        invalid = client.post("/orders", json={"category": "grocery"})
        assert invalid.status_code == 422

    with sqlite3.connect(module.DB_PATH) as db:
        row = db.execute(
            "SELECT product_id,delivery_id,quantity,total_cents,remaining_stock FROM orders WHERE idempotency_key=?",
            ("tea-order",),
        ).fetchone()
        stock = db.execute(
            "SELECT stock FROM products WHERE product_id=?", (receipt.product_id,)
        ).fetchone()[0]
        assert row == (
            receipt.product_id,
            receipt.delivery_id,
            2,
            receipt.total_cents,
            receipt.remaining_stock,
        )
        initial = 8 if receipt.product_id == "tea" else 5
        assert stock == initial - 2
        assert db.execute(
            "SELECT count(*) FROM orders WHERE idempotency_key='tea-order'"
        ).fetchone() == (1,)
    assert calls


def test_write_rejects_delivery_from_another_product_without_effect(tmp_path):
    module = load_app(tmp_path, "invalid_delivery_example")
    tea = module.Product(product_id="tea", name="Tea", category="grocery", stock=8)
    wrong = module.Delivery(
        delivery_id="coffee-ground",
        product_id="coffee",
        name="Ground courier",
        price_cents=350,
    )
    with pytest.raises(ValueError, match="does not belong"):
        module.persist_order(tea, wrong, 1, "wrong-delivery")
    with sqlite3.connect(module.DB_PATH) as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone() == (0,)
        assert db.execute(
            "SELECT stock FROM products WHERE product_id='tea'"
        ).fetchone() == (8,)


def test_categories_cover_empty_single_and_multiple_domains(tmp_path):
    module = load_app(tmp_path, "candidate_domains_example")
    assert module.find_products("stationery") == []
    assert len(module.find_products("stationery")) == 0
    assert [p.product_id for p in module.find_products("coffee")] == ["coffee"]
    assert [p.product_id for p in module.find_products("grocery")] == [
        "tea",
        "tea-green",
    ]
    assert [
        d.delivery_id
        for d in module.compatible_deliveries(module.find_products("coffee")[0])
    ] == ["coffee-ground"]
    tea = next(p for p in module.find_products("grocery") if p.product_id == "tea")
    assert [d.delivery_id for d in module.compatible_deliveries(tea)] == [
        "tea-express",
        "tea-ground",
    ]
