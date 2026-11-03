"""Choose one eligible supplier, run bounded checks, verify, and persist a report."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
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
        "CHOICE_STAGE_DB",
        str(Path.home() / ".cache" / "summonpot" / "choice-stage.sqlite3"),
    )
)


class ReviewRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    review_id: str = Field(min_length=1, max_length=100)


class Supplier(BaseModel):
    identifier: str
    name: str
    category: str
    price_cents: int


class SelectedSupplier(BaseModel):
    review_id: str
    identifier: str
    name: str
    category: str


class CheckResult(BaseModel):
    review_id: str
    supplier_id: str
    check: Check
    passed: bool
    observed: str


class VerifiedReview(BaseModel):
    review_id: str
    supplier_id: str
    supplier_name: str
    checks: list[CheckResult]
    approved: bool


class ReviewReport(VerifiedReview):
    """Canonical persisted endpoint response, distinct from verification output."""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def initialize_database() -> None:
    with closing(connect()) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                identifier TEXT PRIMARY KEY, name TEXT NOT NULL,
                category TEXT NOT NULL, stock INTEGER NOT NULL,
                price_cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_checks (
                review_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
                check_name TEXT NOT NULL, passed INTEGER NOT NULL,
                observed TEXT NOT NULL,
                PRIMARY KEY (review_id, supplier_id, check_name)
            );
            CREATE TABLE IF NOT EXISTS review_reports (
                review_id TEXT PRIMARY KEY, report_json TEXT NOT NULL
            );
            """
        )
        db.executemany(
            "INSERT OR IGNORE INTO suppliers VALUES (?, ?, ?, ?, ?)",
            [
                ("S-101", "Northstar Supply", "paper", 42, 825),
                ("S-202", "Maple Wholesale", "paper", 0, 975),
                ("S-303", "Cedar Office", "office", 19, 650),
            ],
        )
        db.commit()


def find_suppliers(category: str) -> list[Supplier]:
    """Return the actual suppliers available in the requested category."""
    initialize_database()
    with closing(connect()) as db:
        rows = db.execute(
            "SELECT identifier, name, category, price_cents FROM suppliers "
            "WHERE category = ? ORDER BY identifier LIMIT 20",
            (category,),
        ).fetchall()
    return [Supplier(**dict(row)) for row in rows]


def prepare_supplier(supplier: Supplier, review_id: str) -> SelectedSupplier:
    """Return a canonical selected-supplier snapshot for subsequent checks."""
    return SelectedSupplier(
        review_id=review_id,
        identifier=supplier.identifier,
        name=supplier.name,
        category=supplier.category,
    )


def inspect_supplier(review_id: str, supplier_id: str, check: Check) -> CheckResult:
    """Run one closed check against the selected supplier and store its facts."""
    initialize_database()
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT stock, price_cents FROM suppliers WHERE identifier = ?",
            (supplier_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Selected supplier is no longer available")
        if check == "stock":
            passed = row["stock"] > 0
            observed = f"stock={row['stock']}"
        else:
            passed = row["price_cents"] <= 900
            observed = f"price_cents={row['price_cents']}"
        db.execute(
            "INSERT INTO review_checks VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(review_id, supplier_id, check_name) DO UPDATE SET "
            "passed=excluded.passed, observed=excluded.observed",
            (review_id, supplier_id, check, int(passed), observed),
        )
        db.commit()
    return CheckResult(
        review_id=review_id,
        supplier_id=supplier_id,
        check=check,
        passed=passed,
        observed=observed,
    )


def verify_review(
    review_id: str, supplier_id: str, supplier_name: str, final_check: Check
) -> VerifiedReview:
    """Recheck actual business facts and deny incomplete or inconsistent reviews."""
    with closing(connect()) as db:
        supplier = db.execute(
            "SELECT stock, price_cents FROM suppliers WHERE identifier = ?",
            (supplier_id,),
        ).fetchone()
        rows = db.execute(
            "SELECT check_name, passed, observed FROM review_checks "
            "WHERE review_id = ? AND supplier_id = ? ORDER BY check_name",
            (review_id, supplier_id),
        ).fetchall()
    if supplier is None:
        raise ValueError("Selected supplier is no longer available")
    checks = [
        CheckResult(
            review_id=review_id,
            supplier_id=supplier_id,
            check=row["check_name"],
            passed=bool(row["passed"]),
            observed=row["observed"],
        )
        for row in rows
    ]
    facts = {"stock": supplier["stock"] > 0, "prices": supplier["price_cents"] <= 900}
    complete = {item.check for item in checks} == set(facts) and final_check in {
        item.check for item in checks
    }
    consistent = all(item.passed == facts[item.check] for item in checks)
    return VerifiedReview(
        review_id=review_id,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        checks=checks,
        approved=complete and consistent and all(facts.values()),
    )


def persist_report(
    review_id: str,
    supplier_id: str,
    supplier_name: str,
    checks: list[CheckResult],
    approved: bool,
) -> ReviewReport:
    """Persist and read back the exact application-verified report."""
    report = ReviewReport(
        review_id=review_id,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        checks=checks,
        approved=approved,
    )
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO review_reports VALUES (?, ?) "
            "ON CONFLICT(review_id) DO UPDATE SET report_json=excluded.report_json",
            (review_id, report.model_dump_json()),
        )
        stored = db.execute(
            "SELECT report_json FROM review_reports WHERE review_id = ?", (review_id,)
        ).fetchone()["report_json"]
        db.commit()
    return ReviewReport.model_validate_json(stored)


supplier_query = Operation(
    find_suppliers,
    bind={"category": FromRequest("category")},
    output=list[Supplier],
)
select_supplier = Operation(
    prepare_supplier,
    bind={
        "supplier": AgentChoice(from_result=supplier_query),
        "review_id": FromRequest("review_id"),
    },
    output=SelectedSupplier,
    after=(supplier_query,),
)
check_supplier = Operation(
    inspect_supplier,
    bind={
        "review_id": FromResult(select_supplier, "review_id"),
        "supplier_id": FromResult(select_supplier, "identifier"),
        "check": AgentChoice(),
    },
    output=CheckResult,
)
verify_report = Operation(
    verify_review,
    bind={
        "review_id": FromResult(check_supplier, "review_id", invocation="final"),
        "supplier_id": FromResult(check_supplier, "supplier_id", invocation="final"),
        "supplier_name": FromResult(select_supplier, "name"),
        "final_check": FromResult(check_supplier, "check", invocation="final"),
    },
    output=VerifiedReview,
)
persist_review = Operation(
    persist_report,
    bind={
        field: FromResult(verify_report, field)
        for field in ("review_id", "supplier_id", "supplier_name", "checks", "approved")
    },
    output=ReviewReport,
)

summon = Summon("supplier-choice-stage")


@summon("/supplier-reviews")
def review_suppliers(
    request: ReviewRequest,
    candidates=Required(supplier_query, calls=Exactly(1)),
    selected=Required(select_supplier, calls=Exactly(1)),
    checks=Required(check_supplier, calls=Between(1, 3)),
    verified=Required(verify_report, calls=Exactly(1)),
    report=Required(persist_review, calls=Exactly(1)),
) -> ReviewReport:
    """Choose the lowest-price candidate, then run both stock and prices checks.

    Invoke each check at least once before finishing, within three invocations.
    Application code verifies current facts and persists approval or denial.
    """
    ...


if __name__ == "__main__":
    initialize_database()
    summon.serve(host="127.0.0.1", port=8000)
