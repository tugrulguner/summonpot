"""Real application failures and late worker effects never authorize progression."""

import asyncio
import sqlite3
import threading
from typing import Literal

import pytest
from test_checkpoint import (
    CheckedStatus,
    CheckpointRequest,
    RefreshReceipt,
    StatusReport,
)
from test_checkpoint_examples import fixture_runtime

import summonpot.runtime as runtime_module
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
from summonpot.runtime import _OperationOutputError


def failure_app(
    path, phase, *, entered=None, release=None, finished=None, asynchronous=False
):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE effects (kind TEXT)")
    starts = []

    def effect(kind):
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO effects VALUES (?)", (kind,))

    def revision():
        with sqlite3.connect(path) as db:
            return db.execute(
                "SELECT count(*) FROM effects WHERE kind='advance'"
            ).fetchone()[0]

    def probe(key: str) -> CheckedStatus:
        starts.append("probe")
        if phase == "probe":
            raise RuntimeError("controlled probe failure")
        value = revision()
        if phase == "check-output":
            return {"key": key, "accepted": "yes", "revision": value}  # type: ignore[return-value]
        return CheckedStatus(key=key, accepted=value >= 1, revision=value)

    def advance(key: str, pace: Literal["normal", "accelerated"]) -> RefreshReceipt:
        starts.append("advance")
        effect("advance")
        if entered is not None:
            entered.set()
            try:
                assert release is not None and release.wait(3)
            finally:
                assert finished is not None
                finished.set()
        if phase == "advance":
            raise RuntimeError("controlled continuation failure after commit")
        if phase == "advance-output":
            return {"revision": "invalid"}  # type: ignore[return-value]
        return RefreshReceipt(revision=revision())

    async def async_advance(
        key: str, pace: Literal["normal", "accelerated"]
    ) -> RefreshReceipt:
        starts.append("advance")
        effect("advance")
        assert entered is not None
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled application resumed")

    def persist(key: str, accepted: bool, revision: int) -> StatusReport:
        starts.append("persist")
        if phase == "terminal-before":
            raise RuntimeError("controlled terminal precommit failure")
        effect("report")
        if phase == "terminal-after":
            raise RuntimeError("controlled terminal postcommit failure")
        if phase == "terminal-output":
            return {"key": key, "accepted": accepted, "revision": "invalid"}  # type: ignore[return-value]
        return StatusReport(key=key, accepted=accepted, revision=revision)

    check = Operation(probe, bind={"key": FromRequest("key")}, output=CheckedStatus)
    change = Operation(
        async_advance if asynchronous else advance,
        bind={"key": FromResult(check, "key"), "pace": AgentChoice()},
        output=RefreshReceipt,
    )
    terminal = Operation(
        persist,
        bind={
            name: FromResult(check, name, invocation="final")
            for name in ("key", "accepted", "revision")
        },
        output=StatusReport,
    )
    turns = []
    app = Summon("failure-checkpoint", runtime=fixture_runtime(turns))

    @app("/status")
    def endpoint(
        request: CheckpointRequest,
        checked=Required(check, calls=Between(1, 3), until="accepted"),
        changed=Depends(change, calls=AtMost(2)),
        saved=Required(terminal, calls=Exactly(1)),
    ) -> StatusReport:
        """Advance until application verification then persist the checked result."""
        ...

    return app, starts, turns


def capture_run(monkeypatch):
    runs = []
    original = runtime_module._invoke_bound_operation

    async def capture(tool, run, supplied, **kwargs):
        if not runs:
            runs.append(run)
        return await original(tool, run, supplied, **kwargs)

    monkeypatch.setattr(runtime_module, "_invoke_bound_operation", capture)
    return runs


def effects(path):
    with sqlite3.connect(path) as db:
        return [r[0] for r in db.execute("SELECT kind FROM effects ORDER BY rowid")]


@pytest.mark.parametrize(
    "phase,expected_starts,expected_effects,error",
    [
        ("probe", ["probe"], [], RuntimeError),
        ("check-output", ["probe"], [], _OperationOutputError),
        ("advance", ["probe", "advance"], ["advance"], RuntimeError),
        ("advance-output", ["probe", "advance"], ["advance"], _OperationOutputError),
        (
            "terminal-before",
            ["probe", "advance", "probe", "persist"],
            ["advance"],
            RuntimeError,
        ),
        (
            "terminal-after",
            ["probe", "advance", "probe", "persist"],
            ["advance", "report"],
            RuntimeError,
        ),
        (
            "terminal-output",
            ["probe", "advance", "probe", "persist"],
            ["advance", "report"],
            _OperationOutputError,
        ),
    ],
)
def test_phase_failure_retains_effects_without_replay(
    tmp_path, monkeypatch, phase, expected_starts, expected_effects, error
):
    path = tmp_path / "effects.sqlite"
    app, starts, _ = failure_app(path, phase)
    runs = capture_run(monkeypatch)
    with pytest.raises(error):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert starts == expected_starts
    assert effects(path) == expected_effects
    run = runs[0]
    assert run.checkpoint_aborted and run.checkpoint_expected is None
    assert sum(s.started for s in run.states) == len(expected_starts)
    assert all(s.running == 0 for s in run.states)


@pytest.mark.parametrize(
    "asynchronous,timeout", [(True, False), (False, False), (False, True)]
)
def test_cancelled_continuation_cannot_publish_late_worker_result(
    tmp_path, monkeypatch, asynchronous, timeout
):
    path = tmp_path / "effects.sqlite"
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    app, starts, _ = failure_app(
        path,
        "blocked",
        entered=entered,
        release=release,
        finished=finished,
        asynchronous=asynchronous,
    )
    if timeout:
        app._runtime.timeout = 0.2
    runs = capture_run(monkeypatch)

    async def exercise():
        task = asyncio.create_task(app._runtime.call(app.endpoints[0], {"key": "A"}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if not timeout:
                task.cancel()
            with pytest.raises(TimeoutError if timeout else asyncio.CancelledError):
                await task
            assert runs[0].checkpoint_aborted
        finally:
            release.set()
        if not asynchronous:
            assert await asyncio.to_thread(finished.wait, 2)
        await asyncio.sleep(0)

    asyncio.run(exercise())
    assert starts == ["probe", "advance"]
    assert effects(path) == ["advance"]
    run = runs[0]
    assert run.checkpoint_aborted and run.checkpoint_expected is None
    assert sum(s.started for s in run.states) == 2
    assert sum(s.succeeded for s in run.states) == 1
    assert all(s.running == 0 for s in run.states)
