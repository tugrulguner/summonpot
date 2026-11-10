"""Public contract coverage for callable defaults and Annotated metadata."""

import asyncio
import runpy
import sys
from pathlib import Path
from typing import get_type_hints

import pytest
from fastapi.testclient import TestClient

from summonpot.server import build_app

SOURCE = Path(__file__).resolve().parents[1] / "examples/22_contract_defaults/app.py"


def test_quote_uses_application_default_without_a_model(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "invalid:no-provider")
    ns = runpy.run_path(str(SOURCE))
    summon = ns["summon"]
    client = TestClient(build_app(summon))
    response = client.post(
        "/quotes/defaults", json={"unit_price_cents": 199, "quantity": 3}
    )
    assert response.status_code == 200
    assert response.json() == {
        "subtotal_cents": 597,
        "discount_cents": 29,
        "total_cents": 568,
    }
    assert summon._runtime._agents == {}
    assert "discount_percent" not in ns["quote_operation"].bind
    assert (
        get_type_hints(ns["calculate_quote"], include_extras=True)["return"]
        == ns["QuoteOutput"]
    )
    assert summon.endpoints[0].output_annotation == ns["QuoteOutput"]
    schema = client.get("/openapi.json").json()
    assert (
        schema["paths"]["/quotes/defaults"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["description"]
        == "Quote after the application discount."
    )


def test_receiving_constraint_rejects_before_callable_starts(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "invalid:no-provider")
    ns = runpy.run_path(str(SOURCE))
    # This value is legal in the request, but outside the receiving operation.
    ns["QuoteRequest"](unit_price_cents=199, quantity=11)
    starts = []

    def profile(frame, event, arg):
        if event == "call" and frame.f_code is ns["calculate_quote"].__code__:
            starts.append(True)

    # Async callable executes on this thread; observe it without replacing the contract.
    previous = sys.getprofile()
    sys.setprofile(profile)
    try:

        async def call():
            return await ns["summon"]._runtime.call(
                ns["summon"].endpoints[0], {"unit_price_cents": 199, "quantity": 11}
            )

        asyncio.run(ns["calculate_quote"](199, 3))
        assert starts == [True]
        starts.clear()
        with pytest.raises(RuntimeError, match="receiving"):
            asyncio.run(call())
    finally:
        sys.setprofile(previous)
    assert starts == []
    client = TestClient(build_app(ns["summon"]))
    response = client.post(
        "/quotes/defaults", json={"unit_price_cents": 199, "quantity": 11}
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request data did not satisfy a receiving operation contract."
    }
    assert (
        client.post(
            "/quotes/defaults",
            json={"unit_price_cents": 199, "quantity": 3, "discount_percent": 90},
        ).status_code
        == 422
    )
    assert ns["summon"]._runtime._agents == {}
