"""Prepare an order, run bounded checks, verify policy, and persist its report."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from summonpot import (
    AgentChoice,
    Between,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)

Check = Literal["stock", "prices"]
DB_PATH = Path(
    os.environ.get(
        "STAGE_CHAIN_DB",
        str(Path.home() / ".cache" / "summonpot" / "stage-chain.sqlite3"),
    )
)


class ReviewRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)


class PreparedOrder(BaseModel):
    order_id: str
    sku: str
    quantity: int
    required_checks: list[Check]


class CheckSnapshot(BaseModel):
    order_id: str
    sku: str
    quantity: int
    check: Check
    passed: bool
    detail: str


class VerifiedDecision(BaseModel):
    order_id: str
    sku: str
    quantity: int
    checks: list[Check]
    approved: bool
    reasons: list[str]


class ReviewReport(BaseModel):
    review_id: str
    order_id: str
    sku: str
    quantity: int
    checks: list[Check]
    approved: bool
    reasons: list[str]


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize_database() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, sku TEXT NOT NULL, quantity INTEGER NOT NULL,
                review_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inventory (
                sku TEXT PRIMARY KEY, stock INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL,
                approved_price_cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_checks (
                review_id TEXT NOT NULL, check_name TEXT NOT NULL, passed INTEGER NOT NULL,
                detail TEXT NOT NULL, PRIMARY KEY (review_id, check_name)
            );
            CREATE TABLE IF NOT EXISTS review_reports (
                review_id TEXT PRIMARY KEY, report_json TEXT NOT NULL
            );
        """)
        db.executemany(
            "INSERT OR IGNORE INTO inventory VALUES (?, ?, ?, ?)",
            [
                ("BOOK-1", 12, 2499, 2499),
                ("MUG-2", 1, 1599, 1499),
            ],
        )
        db.execute(
            "INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?)",
            ("order-valid", "BOOK-1", 2, "review-valid"),
        )
        db.execute(
            "INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?)",
            ("order-stock-fail", "MUG-2", 3, "review-stock-fail"),
        )


def load_order(order_id: str) -> PreparedOrder:
    """Load the fixed order and its required business checks."""
    initialize_database()
    with connect() as db:
        order = db.execute(
            "SELECT order_id, sku, quantity, review_id FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise ValueError("unknown order")
    return PreparedOrder(
        order_id=order["order_id"],
        sku=order["sku"],
        quantity=order["quantity"],
        required_checks=["stock", "prices"],
    )


def run_check(order_id: str, sku: str, quantity: int, check: Check) -> CheckSnapshot:
    """Run one selected, fixed business check and persist its observed result."""
    initialize_database()
    with connect() as db:
        order = db.execute(
            "SELECT review_id FROM orders WHERE order_id = ? AND sku = ? AND quantity = ?",
            (order_id, sku, quantity),
        ).fetchone()
        item = db.execute(
            "SELECT stock, unit_price_cents, approved_price_cents FROM inventory WHERE sku = ?",
            (sku,),
        ).fetchone()
        if order is None or item is None:
            raise ValueError("order facts unavailable")
        if check == "stock":
            passed = item["stock"] >= quantity
            detail = f"available={item['stock']}; requested={quantity}"
        else:
            passed = item["unit_price_cents"] == item["approved_price_cents"]
            detail = f"unit_price_cents={item['unit_price_cents']}; approved={item['approved_price_cents']}"
        db.execute(
            "INSERT INTO review_checks VALUES (?, ?, ?, ?) ON CONFLICT(review_id, check_name) DO UPDATE SET passed=excluded.passed, detail=excluded.detail",
            (order["review_id"], check, int(passed), detail),
        )
    return CheckSnapshot(
        order_id=order_id,
        sku=sku,
        quantity=quantity,
        check=check,
        passed=passed,
        detail=detail,
    )


def verify_review(
    order_id: str,
    sku: str,
    quantity: int,
    expected_checks: list[Check],
    final_check: Check,
) -> VerifiedDecision:
    """Independently verify selected check facts; incomplete checks can never approve."""
    initialize_database()
    with connect() as db:
        order = db.execute(
            "SELECT review_id FROM orders WHERE order_id = ? AND sku = ? AND quantity = ?",
            (order_id, sku, quantity),
        ).fetchone()
        item = db.execute(
            "SELECT stock, unit_price_cents, approved_price_cents FROM inventory WHERE sku = ?",
            (sku,),
        ).fetchone()
        rows = (
            db.execute(
                "SELECT check_name, passed FROM review_checks WHERE review_id = ?",
                (order["review_id"],),
            ).fetchall()
            if order
            else []
        )
    recorded = {row["check_name"]: bool(row["passed"]) for row in rows}
    checks: list[Check] = [name for name in ("stock", "prices") if name in recorded]  # type: ignore[misc]
    reasons: list[str] = []
    if final_check not in recorded:
        reasons.append("final repeated-stage invocation is not persisted")
    if set(checks) != set(recorded):
        reasons.append("selected checks do not match persisted check records")
    if set(recorded) != set(expected_checks):
        reasons.append("required checks were not all completed")
    if item is None or order is None:
        reasons.append("order facts unavailable")
    else:
        facts = {
            "stock": item["stock"] >= quantity,
            "prices": item["unit_price_cents"] == item["approved_price_cents"],
        }
        if any(
            recorded.get(name) != fact
            for name, fact in facts.items()
            if name in recorded
        ):
            reasons.append("persisted check result differs from current business facts")
        if any(not value for value in facts.values()):
            reasons.append("one or more deterministic business checks failed")
    return VerifiedDecision(
        order_id=order_id,
        sku=sku,
        quantity=quantity,
        checks=checks,
        approved=not reasons,
        reasons=reasons,
    )


def persist_report(
    order_id: str,
    sku: str,
    quantity: int,
    checks: list[Check],
    approved: bool,
    reasons: list[str],
) -> ReviewReport:
    """Persist, read back, and return the canonical application-owned JSON report."""
    initialize_database()
    with connect() as db:
        row = db.execute(
            "SELECT review_id FROM orders WHERE order_id = ? AND sku = ? AND quantity = ?",
            (order_id, sku, quantity),
        ).fetchone()
        if row is None:
            raise ValueError("unknown order facts")
        report = ReviewReport(
            review_id=row["review_id"],
            order_id=order_id,
            sku=sku,
            quantity=quantity,
            checks=checks,
            approved=approved,
            reasons=reasons,
        )
        db.execute(
            "INSERT INTO review_reports VALUES (?, ?) ON CONFLICT(review_id) DO UPDATE SET report_json=excluded.report_json",
            (report.review_id, report.model_dump_json()),
        )
        stored = db.execute(
            "SELECT report_json FROM review_reports WHERE review_id = ?",
            (report.review_id,),
        ).fetchone()[0]
    return ReviewReport.model_validate_json(stored)


prepare_op = Operation(
    load_order, bind={"order_id": FromRequest("order_id")}, output=PreparedOrder
)
check_op = Operation(
    run_check,
    bind={
        "order_id": FromResult(prepare_op, "order_id"),
        "sku": FromResult(prepare_op, "sku"),
        "quantity": FromResult(prepare_op, "quantity"),
        "check": AgentChoice(),
    },
    output=CheckSnapshot,
)
verify_op = Operation(
    verify_review,
    bind={
        "order_id": FromResult(check_op, "order_id", invocation="final"),
        "sku": FromResult(check_op, "sku", invocation="final"),
        "quantity": FromResult(check_op, "quantity", invocation="final"),
        "expected_checks": FromResult(prepare_op, "required_checks"),
        "final_check": FromResult(check_op, "check", invocation="final"),
    },
    output=VerifiedDecision,
)
report_op = Operation(
    persist_report,
    bind={
        "order_id": FromResult(verify_op, "order_id"),
        "sku": FromResult(verify_op, "sku"),
        "quantity": FromResult(verify_op, "quantity"),
        "checks": FromResult(verify_op, "checks"),
        "approved": FromResult(verify_op, "approved"),
        "reasons": FromResult(verify_op, "reasons"),
    },
    output=ReviewReport,
)
summon = Summon("order-review")


@summon("/reviews")
def review_order(
    request: ReviewRequest,
    prepared=Required(prepare_op, calls=Exactly(1)),
    inspection=Required(check_op, calls=Between(1, 3)),
    verified=Required(verify_op, calls=Exactly(1)),
    report=Required(report_op, calls=Exactly(1)),
) -> ReviewReport:
    """Review an order with bounded stock/price checks and persist a verified decision."""
    ...


if __name__ == "__main__":
    initialize_database()
    summon.serve(host="127.0.0.1", port=8000)
