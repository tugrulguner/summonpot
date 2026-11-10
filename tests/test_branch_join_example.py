"""Executable acceptance of example20; calculations are independent reference oracles."""

import asyncio
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from summonpot.server import build_app

ROOT = Path(__file__).resolve().parents[1]


def _load(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "invalid:no-provider")
    return runpy.run_path(str(ROOT / "examples/20_branch_join/app.py"))["summon"]


def _expected(unit_price, quantity, unit_weight):
    blocks, remainder = divmod(max(0, unit_weight * quantity - 500), 500)
    shipping = 499 + 199 * (blocks + bool(remainder))
    return {
        "subtotal_cents": unit_price * quantity,
        "shipping_cents": shipping,
        "total_cents": unit_price * quantity + shipping,
    }


@pytest.mark.parametrize("weight", [1, 499, 500, 501, 1000, 1001])
def test_example_tariff_boundaries_through_http(monkeypatch, weight):
    app = _load(monkeypatch)
    with TestClient(build_app(app)) as client:
        response = client.post(
            "/quotes/combined",
            json={"unit_price_cents": 1299, "quantity": 1, "unit_weight_grams": weight},
        )
    assert response.status_code == 200
    assert response.json() == _expected(1299, 1, weight)
    assert app._runtime._agents == {}


def test_example_concurrent_requests_do_not_mix_branch_results(monkeypatch):
    app = _load(monkeypatch)
    endpoint = app.endpoints[0]

    async def run():
        return await asyncio.gather(
            *(
                app._runtime.call(
                    endpoint,
                    {"unit_price_cents": 99, "quantity": n, "unit_weight_grams": 250},
                )
                for n in range(1, 17)
            )
        )

    results = asyncio.run(run())
    assert [result.model_dump() for result in results] == [
        _expected(99, n, 250) for n in range(1, 17)
    ]
    assert app._runtime._agents == {}


def test_example_invalid_request_is_rejected_without_a_model(monkeypatch):
    app = _load(monkeypatch)
    with TestClient(build_app(app)) as client:
        response = client.post(
            "/quotes/combined",
            json={"unit_price_cents": -1, "quantity": 0, "unit_weight_grams": 0},
        )
    assert response.status_code == 422
    assert app._runtime._agents == {}
