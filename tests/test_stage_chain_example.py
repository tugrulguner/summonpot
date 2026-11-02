"""Acceptance tests for example 16 using the real runtime and local SQLite."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

ROOT = Path(__file__).resolve().parents[1]


def load_app(tmp_path, decisions):
    db_path = tmp_path / "review.sqlite3"
    spec = importlib.util.spec_from_file_location(
        "example16_app", ROOT / "examples/16_stage_chain/app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.DB_PATH = db_path
    module.initialize_database()
    queue = iter(decisions)
    turns = []

    def choose(messages, info):
        assert not info.function_tools
        turns.append(1)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(queue))]
        )

    module.summon._runtime = module.summon._runtime.__class__(
        model=FunctionModel(choose), retries=0
    )
    return module, db_path, turns


def decisions_for(*checks):
    return [{"decision": "invoke", "argument_0": check} for check in checks] + [
        {"decision": "finish"}
    ]


def test_valid_order_checks_and_report_are_real_sqlite_effects(tmp_path):
    module, db_path, turns = load_app(tmp_path, decisions_for("stock", "prices"))
    report = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"order_id": "order-valid"}
        )
    )
    assert report == module.ReviewReport(
        review_id="review-valid",
        order_id="order-valid",
        sku="BOOK-1",
        quantity=2,
        checks=["stock", "prices"],
        approved=True,
        reasons=[],
    )
    assert len(turns) == 3
    with sqlite3.connect(db_path) as db:
        stored = json.loads(
            db.execute(
                "SELECT report_json FROM review_reports WHERE review_id = ?",
                ("review-valid",),
            ).fetchone()[0]
        )
        checks = db.execute(
            "SELECT check_name, passed FROM review_checks WHERE review_id = ? ORDER BY check_name",
            ("review-valid",),
        ).fetchall()
    assert stored == report.model_dump(mode="json")
    assert checks == [("prices", 1), ("stock", 1)]


def test_incomplete_checks_never_approve_and_duplicates_do_not_add_facts(tmp_path):
    module, db_path, turns = load_app(tmp_path, decisions_for("stock"))
    report = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"order_id": "order-valid"}
        )
    )
    assert report.checks == ["stock"]
    assert report.approved is False
    assert any("not all completed" in reason for reason in report.reasons)
    assert len(turns) == 2
    with sqlite3.connect(db_path) as db:
        checks = db.execute(
            "SELECT check_name FROM review_checks WHERE review_id = ?",
            ("review-valid",),
        ).fetchall()
        stored = json.loads(
            db.execute(
                "SELECT report_json FROM review_reports WHERE review_id = ?",
                ("review-valid",),
            ).fetchone()[0]
        )
    assert checks == [("stock",)]
    assert stored["approved"] is False


def test_duplicate_choice_is_not_an_additional_check(tmp_path):
    module, db_path, turns = load_app(tmp_path, decisions_for("stock", "stock"))
    report = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"order_id": "order-valid"}
        )
    )
    assert report.checks == ["stock"]
    assert report.approved is False
    assert len(turns) == 3
    with sqlite3.connect(db_path) as db:
        checks = db.execute(
            "SELECT check_name FROM review_checks WHERE review_id = ?",
            ("review-valid",),
        ).fetchall()
    assert checks == [("stock",)]


def test_review_after_partial_prior_checks_can_complete_required_policy(tmp_path):
    module, db_path, _ = load_app(tmp_path, decisions_for("stock"))
    first = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"order_id": "order-valid"}
        )
    )
    assert first.approved is False
    queue = iter(decisions_for("stock", "prices"))

    def choose(messages, info):
        assert not info.function_tools
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(queue))]
        )

    module.summon._runtime = module.summon._runtime.__class__(
        model=FunctionModel(choose), retries=0
    )
    second = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"order_id": "order-valid"}
        )
    )
    assert second.approved is True and second.checks == ["stock", "prices"]
    with sqlite3.connect(db_path) as db:
        saved = json.loads(
            db.execute(
                "SELECT report_json FROM review_reports WHERE review_id='review-valid'"
            ).fetchone()[0]
        )
    assert saved == second.model_dump(mode="json")


def test_stock_failure_cannot_be_approved(tmp_path):
    module, _, _ = load_app(tmp_path, decisions_for("prices", "stock"))
    report = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"order_id": "order-stock-fail"}
        )
    )
    assert report.approved is False
    assert any("business checks failed" in reason for reason in report.reasons)
