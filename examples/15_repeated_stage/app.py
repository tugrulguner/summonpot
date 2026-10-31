"""A bounded repeated audit stage followed by an application-owned report write."""

from __future__ import annotations

import json
import os
import sqlite3
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

Check = Literal["stock", "prices", "deliveries"]
DB_PATH = Path(
    os.environ.get(
        "REPEATED_STAGE_DB",
        str(Path.home() / ".cache" / "summonpot" / "repeated-stage.sqlite3"),
    )
)


class AuditRequest(BaseModel):
    audit_id: str = Field(min_length=1, max_length=100)


class Finding(BaseModel):
    check: Check
    anomaly_count: int
    details: list[str]


class Snapshot(BaseModel):
    audit_id: str
    checks: list[Check]
    findings: list[Finding]


class AuditReport(BaseModel):
    audit_id: str
    checks: list[Check]
    findings: list[Finding]
    finding_count: int


def connect() -> sqlite3.Connection:
    """Open an application-owned SQLite connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def initialize_database() -> None:
    """Create schema and seed only missing rows; never reset existing data."""
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS stock_items (
                sku TEXT PRIMARY KEY, recorded INTEGER NOT NULL, counted INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prices (
                sku TEXT PRIMARY KEY, listed_cents INTEGER NOT NULL, approved_cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS delivery_zones (
                zone TEXT PRIMARY KEY, enabled INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_checks (
                audit_id TEXT NOT NULL, check_name TEXT NOT NULL,
                anomaly_count INTEGER NOT NULL, details_json TEXT NOT NULL,
                PRIMARY KEY (audit_id, check_name)
            );
            CREATE TABLE IF NOT EXISTS audit_reports (
                audit_id TEXT PRIMARY KEY, report_json TEXT NOT NULL
            );
            """
        )
        db.executemany(
            "INSERT OR IGNORE INTO stock_items VALUES (?, ?, ?)",
            [("MUG-1", 12, 10), ("PEN-2", 20, 20)],
        )
        db.executemany(
            "INSERT OR IGNORE INTO prices VALUES (?, ?, ?)",
            [("MUG-1", 1499, 1399), ("PEN-2", 299, 299)],
        )
        db.executemany(
            "INSERT OR IGNORE INTO delivery_zones VALUES (?, ?)",
            [("north", 1), ("island", 0)],
        )


def check_rows(db: sqlite3.Connection, check: Check) -> list[str]:
    queries = {
        "stock": (
            "SELECT sku FROM stock_items WHERE recorded != counted ORDER BY sku",
            "stock count differs",
        ),
        "prices": (
            "SELECT sku FROM prices WHERE listed_cents != approved_cents ORDER BY sku",
            "listed price differs from approved price",
        ),
        "deliveries": (
            "SELECT zone FROM delivery_zones WHERE enabled = 0 ORDER BY zone",
            "delivery zone is disabled",
        ),
    }
    query, message = queries[check]
    return [f"{row[0]}: {message}" for row in db.execute(query).fetchall()]


def inspect_check(audit_id: str, check: Check) -> Snapshot:
    """Record the selected real SQL finding and return the audit's cumulative view."""
    initialize_database()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        details = check_rows(db, check)
        db.execute(
            "INSERT INTO audit_checks VALUES (?, ?, ?, ?) "
            "ON CONFLICT(audit_id, check_name) DO UPDATE SET "
            "anomaly_count = excluded.anomaly_count, details_json = excluded.details_json",
            (audit_id, check, len(details), json.dumps(details)),
        )
        rows = db.execute(
            "SELECT check_name, anomaly_count, details_json FROM audit_checks "
            "WHERE audit_id = ? ORDER BY check_name",
            (audit_id,),
        ).fetchall()
    findings = [
        Finding(
            check=row["check_name"],
            anomaly_count=row["anomaly_count"],
            details=json.loads(row["details_json"]),
        )
        for row in rows
    ]
    return Snapshot(
        audit_id=audit_id,
        checks=[finding.check for finding in findings],
        findings=findings,
    )


def save_report(
    audit_id: str, checks: list[Check], findings: list[Finding]
) -> AuditReport:
    """Persist and return the canonical report read from SQLite."""
    initialize_database()
    report = AuditReport(
        audit_id=audit_id,
        checks=checks,
        findings=findings,
        finding_count=sum(finding.anomaly_count for finding in findings),
    )
    payload = report.model_dump_json()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO audit_reports (audit_id, report_json) VALUES (?, ?) "
            "ON CONFLICT(audit_id) DO UPDATE SET report_json = excluded.report_json",
            (audit_id, payload),
        )
        stored = db.execute(
            "SELECT report_json FROM audit_reports WHERE audit_id = ?", (audit_id,)
        ).fetchone()["report_json"]
    return AuditReport.model_validate_json(stored)


inspect_operation = Operation(
    inspect_check,
    bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
    output=Snapshot,
)
report_operation = Operation(
    save_report,
    bind={
        "audit_id": FromRequest("audit_id"),
        "checks": FromResult(inspect_operation, "checks", invocation="final"),
        "findings": FromResult(inspect_operation, "findings", invocation="final"),
    },
    output=AuditReport,
    after=(inspect_operation,),
)

summon = Summon("repeated-stage-audit")


@summon("/audits")
def audit_inventory(
    request: AuditRequest,
    snapshot=Required(inspect_operation, calls=Between(1, 3)),
    report=Required(report_operation, calls=Exactly(1)),
) -> AuditReport:
    """Run bounded inventory checks and persist a report of the final cumulative snapshot."""
    ...


if __name__ == "__main__":
    initialize_database()
    summon.serve(host="127.0.0.1", port=8000)
