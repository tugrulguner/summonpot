"""A bounded audit endpoint backed by application-owned SQLite checks."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from summonpot import AgentChoice, Between, FromRequest, Operation, Required, Summon

Check = Literal["stock", "prices", "deliveries"]
DB_PATH = Path(
    os.environ.get(
        "BOUNDED_AUDIT_DB",
        str(Path.home() / ".cache" / "summonpot" / "bounded-audit.sqlite3"),
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


def connect() -> sqlite3.Connection:
    """Open a short-lived connection to this application's database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    """Create tables and seed only missing catalog rows; never reset existing state."""
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
                zone TEXT PRIMARY KEY, enabled INTEGER NOT NULL, carrier TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_checks (
                audit_id TEXT NOT NULL, check_name TEXT NOT NULL,
                anomaly_count INTEGER NOT NULL, details_json TEXT NOT NULL,
                PRIMARY KEY (audit_id, check_name)
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
            "INSERT OR IGNORE INTO delivery_zones VALUES (?, ?, ?)",
            [("north", 1, "Northline"), ("island", 0, "Island Post")],
        )


def _check_rows(db: sqlite3.Connection, check: Check) -> list[str]:
    """Run one fixed, whitelisted, parameter-free audit query."""
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


def inspect_inventory(audit_id: str, check: Check) -> Snapshot:
    """Persist one selected audit check and return its canonical cumulative snapshot."""
    initialize_database()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT anomaly_count, details_json FROM audit_checks "
            "WHERE audit_id = ? AND check_name = ?",
            (audit_id, check),
        ).fetchone()
        if prior is None:
            import json

            details = _check_rows(db, check)
            db.execute(
                "INSERT INTO audit_checks VALUES (?, ?, ?, ?)",
                (audit_id, check, len(details), json.dumps(details)),
            )
        else:
            import json

            details = json.loads(prior["details_json"])
        rows = db.execute(
            "SELECT check_name, anomaly_count, details_json FROM audit_checks "
            "WHERE audit_id = ? ORDER BY check_name",
            (audit_id,),
        ).fetchall()
    import json

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


inspect_operation = Operation(
    inspect_inventory,
    bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
    output=Snapshot,
)

summon = Summon("bounded-sqlite-audit")


@summon("/audits")
def audit_inventory(
    request: AuditRequest,
    snapshot=Required(inspect_operation, calls=Between(1, 3)),
) -> Snapshot:
    """Run selected bounded inventory checks and return the cumulative final snapshot."""
    ...


if __name__ == "__main__":
    initialize_database()
    summon.serve(host="127.0.0.1", port=8000)
