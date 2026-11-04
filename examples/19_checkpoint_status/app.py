"""A three-operation checkpoint/refresh endpoint with real persisted state."""

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
        "CHECKPOINT_STATUS_DB",
        str(Path.home() / ".cache/summonpot/checkpoint-status.sqlite3"),
    )
)
Pace = Literal["normal", "accelerated"]


class StatusRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)


class JobSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    job_id: str
    revision: int
    completed: int
    target: int


class CheckedStatus(BaseModel):
    snapshot: JobSnapshot
    accepted: StrictBool


class RefreshReceipt(BaseModel):
    job_id: str
    revision: int
    pace: Pace


class StatusReport(BaseModel):
    job_id: str
    revision: int
    completed: int
    target: int
    status: Literal["verified", "unresolved"]


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
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                completed INTEGER NOT NULL, target INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS refreshes (
                job_id TEXT, revision INTEGER, pace TEXT,
                PRIMARY KEY(job_id, revision));
            CREATE TABLE IF NOT EXISTS reports (
                job_id TEXT PRIMARY KEY, report_json TEXT NOT NULL);
        """)
        db.executemany(
            "INSERT OR IGNORE INTO jobs VALUES (?,0,?,?)",
            [
                ("complete", 2, 2),
                ("pending", 0, 2),
                ("exhausted", 0, 5),
            ],
        )


def read_checkpoint(job_id: str) -> CheckedStatus:
    initialize_database()
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown job")
    snapshot = JobSnapshot(**dict(row))
    return CheckedStatus(
        snapshot=snapshot, accepted=snapshot.completed >= snapshot.target
    )


def refresh_job(snapshot: JobSnapshot, pace: Pace) -> RefreshReceipt:
    increment = 1 if pace == "normal" else 2
    with database() as db:
        changed = db.execute(
            "UPDATE jobs SET completed=completed+?,revision=revision+1 WHERE job_id=? AND revision=?",
            (increment, snapshot.job_id, snapshot.revision),
        ).rowcount
        if changed != 1:
            raise ValueError("Stale job revision")
        db.execute(
            "INSERT INTO refreshes VALUES (?,?,?)",
            (snapshot.job_id, snapshot.revision + 1, pace),
        )
    return RefreshReceipt(
        job_id=snapshot.job_id, revision=snapshot.revision + 1, pace=pace
    )


def persist_status(snapshot: JobSnapshot, accepted: StrictBool) -> StatusReport:
    report = StatusReport(
        job_id=snapshot.job_id,
        revision=snapshot.revision,
        completed=snapshot.completed,
        target=snapshot.target,
        status="verified" if accepted else "unresolved",
    )
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM jobs WHERE job_id=?", (snapshot.job_id,)
        ).fetchone()
        if row is None or dict(row) != snapshot.model_dump():
            raise ValueError("Checked job changed before persistence")
        db.execute(
            "INSERT INTO reports VALUES (?,?) ON CONFLICT(job_id) DO UPDATE SET report_json=excluded.report_json",
            (snapshot.job_id, report.model_dump_json()),
        )
        stored = db.execute(
            "SELECT report_json FROM reports WHERE job_id=?", (snapshot.job_id,)
        ).fetchone()["report_json"]
    return StatusReport.model_validate_json(stored)


checkpoint = Operation(
    read_checkpoint, bind={"job_id": FromRequest("job_id")}, output=CheckedStatus
)
refresh = Operation(
    refresh_job,
    bind={"snapshot": FromResult(checkpoint, "snapshot"), "pace": AgentChoice()},
    output=RefreshReceipt,
)
final = Operation(
    persist_status,
    bind={
        field: FromResult(checkpoint, field, invocation="final")
        for field in ("snapshot", "accepted")
    },
    output=StatusReport,
)
app = Summon("checkpoint-status")


@app("/checkpoint-status")
def checkpoint_status(
    request: StatusRequest,
    check=Required(checkpoint, calls=Between(1, 3), until="accepted"),
    advance=Depends(refresh, calls=AtMost(2)),
    report=Required(final, calls=Exactly(1)),
) -> StatusReport:
    """Refresh until accepted or the declared limit, preferring normal pace. Persist the actual checked progress, never an invented completion."""
    ...
