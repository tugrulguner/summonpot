"""A fixed endpoint applies safe record cleanups and persists checked facts."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from summonpot import (
    AgentChoice,
    AtMost,
    Between,
    Depends,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)

DB_PATH = Path(
    os.environ.get(
        "CHECKPOINT_CLEANUP_DB",
        str(Path.home() / ".cache/summonpot/checkpoint-cleanup.sqlite3"),
    )
)
Action = Literal["trim_name", "uppercase_sku", "lowercase_email"]


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    record_id: str
    revision: int
    name: str
    sku: str
    email: str


class CleanupRequest(BaseModel):
    record_id: str = Field(min_length=1, max_length=100)


class Inspection(BaseModel):
    snapshot: Record


class Verification(BaseModel):
    snapshot: Record
    accepted: StrictBool
    issues: tuple[str, ...]


class Correction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: Record
    action: Action


class CorrectionReceipt(BaseModel):
    record_id: str
    revision: int
    action: Action


class CleanupReport(BaseModel):
    record_id: str
    revision: int
    status: Literal["verified", "unresolved"]
    issues: tuple[str, ...]


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                record_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                name TEXT NOT NULL, sku TEXT NOT NULL, email TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS corrections (
                record_id TEXT, revision INTEGER, action TEXT,
                PRIMARY KEY(record_id, revision));
            CREATE TABLE IF NOT EXISTS reports (
                record_id TEXT PRIMARY KEY, report_json TEXT NOT NULL);
        """)
        db.executemany(
            "INSERT OR IGNORE INTO records VALUES (?,0,?,?,?)",
            [
                ("valid", "Ada", "SKU-7", "ada@example.com"),
                ("needs-review", " Ada ", "sku-7", "ada@example.com"),
                ("exhausted", " Ada ", "sku-7", "ADA@EXAMPLE.COM"),
            ],
        )


def inspect_record(record_id: str) -> Inspection:
    initialize_database()
    with database() as db:
        row = db.execute(
            "SELECT * FROM records WHERE record_id=?", (record_id,)
        ).fetchone()
    if row is None:
        raise ValueError("Unknown record")
    return Inspection(snapshot=Record(**dict(row)))


def verify_record(snapshot: Record) -> Verification:
    issues = []
    if snapshot.name != snapshot.name.strip():
        issues.append("trim_name")
    if snapshot.sku != snapshot.sku.upper():
        issues.append("uppercase_sku")
    if snapshot.email != snapshot.email.lower():
        issues.append("lowercase_email")
    return Verification(snapshot=snapshot, accepted=not issues, issues=tuple(issues))


def permitted_corrections(
    snapshot: Record, issues: tuple[str, ...]
) -> list[Correction]:
    # These normalization actions preserve this application's record identity.
    allowed: tuple[Action, ...] = ("trim_name", "uppercase_sku", "lowercase_email")
    return [
        Correction(snapshot=snapshot, action=action)
        for action in allowed
        if action in issues
    ]


def apply_correction(correction: Correction) -> CorrectionReceipt:
    snapshot = correction.snapshot
    name, sku, email = snapshot.name, snapshot.sku, snapshot.email
    if correction.action == "trim_name":
        name = name.strip()
    elif correction.action == "uppercase_sku":
        sku = sku.upper()
    else:
        email = email.lower()
    with database() as db:
        changed = db.execute(
            "UPDATE records SET name=?,sku=?,email=?,revision=revision+1 WHERE record_id=? AND revision=?",
            (name, sku, email, snapshot.record_id, snapshot.revision),
        ).rowcount
        if changed != 1:
            raise ValueError("Stale record revision")
        db.execute(
            "INSERT INTO corrections VALUES (?,?,?)",
            (snapshot.record_id, snapshot.revision + 1, correction.action),
        )
    return CorrectionReceipt(
        record_id=snapshot.record_id,
        revision=snapshot.revision + 1,
        action=correction.action,
    )


def persist_report(
    snapshot: Record, accepted: StrictBool, issues: tuple[str, ...]
) -> CleanupReport:
    report = CleanupReport(
        record_id=snapshot.record_id,
        revision=snapshot.revision,
        status="verified" if accepted else "unresolved",
        issues=issues,
    )
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM records WHERE record_id=?", (snapshot.record_id,)
        ).fetchone()
        if row is None or dict(row) != snapshot.model_dump():
            raise ValueError("Checked snapshot changed before persistence")
        db.execute(
            "INSERT INTO reports VALUES (?,?) ON CONFLICT(record_id) DO UPDATE SET report_json=excluded.report_json",
            (snapshot.record_id, report.model_dump_json()),
        )
        stored = db.execute(
            "SELECT report_json FROM reports WHERE record_id=?", (snapshot.record_id,)
        ).fetchone()["report_json"]
    return CleanupReport.model_validate_json(stored)


inspection = Operation(
    inspect_record, bind={"record_id": FromRequest("record_id")}, output=Inspection
)
verification = Operation(
    verify_record,
    bind={"snapshot": FromResult(inspection, "snapshot")},
    output=Verification,
)
options = Operation(
    permitted_corrections,
    bind={field: FromResult(verification, field) for field in ("snapshot", "issues")},
    output=list[Correction],
)
correction = Operation(
    apply_correction,
    bind={"correction": AgentChoice(from_result=options)},
    output=CorrectionReceipt,
)
persistence = Operation(
    persist_report,
    bind={
        field: FromResult(verification, field, invocation="final")
        for field in ("snapshot", "accepted", "issues")
    },
    output=CleanupReport,
)
summon = Summon("checkpoint-cleanup")


@summon("/checkpoint-cleanup")
def cleanup(
    request: CleanupRequest,
    inspect=Required(inspection, calls=Between(1, 3)),
    check=Required(verification, calls=Between(1, 3), until="accepted"),
    available=Depends(options, calls=AtMost(2)),
    change=Depends(correction, calls=AtMost(2)),
    report=Required(persistence, calls=Exactly(1)),
) -> CleanupReport:
    """Apply permitted normalizations until verified or the declared limit. Prefer trim_name before uppercase_sku before lowercase_email. Persist only the actual checked outcome."""
    ...
