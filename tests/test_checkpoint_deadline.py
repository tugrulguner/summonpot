"""Checkpoint finalization shares the absolute request deadline."""

import asyncio
import time

import pytest
from test_checkpoint import CheckedStatus, CheckpointRequest, StatusReport
from test_checkpoint_continuation import application

import summonpot._execution as execution
from summonpot import Exactly, FromRequest, FromResult, Operation, Required, Summon
from summonpot.runtime import Runtime


@pytest.mark.parametrize("path", ["resolved-chain", "checkpoint"])
def test_final_audit_cannot_return_success_after_request_deadline(monkeypatch, path):
    compile_auditor = execution._compile_output_auditor
    audits = []

    def compile_observed(adapter):
        audit = compile_auditor(adapter)

        def slow_audit(value):
            result = audit(value)
            audits.append(1)
            # Keep the real audit; model elapsed synchronous finalization time.
            # asyncio.timeout cannot preempt this or detect it without yielding.
            time.sleep(0.06)
            return result

        return slow_audit

    monkeypatch.setattr(execution, "_compile_output_auditor", compile_observed)
    if path == "checkpoint":
        app, _, _, _ = application(target=0)
        app._runtime.timeout = 0.04
    else:

        def read(key: str) -> CheckedStatus:
            return CheckedStatus(key=key, accepted=True, revision=0)

        def finish(key: str) -> StatusReport:
            return StatusReport(key=key, accepted=True, revision=0)

        first = Operation(read, bind={"key": FromRequest("key")}, output=CheckedStatus)
        last = Operation(
            finish, bind={"key": FromResult(first, "key")}, output=StatusReport
        )
        app = Summon("deadline-control", runtime=Runtime(timeout=0.04))

        @app("/run")
        def endpoint(
            request: CheckpointRequest,
            loaded=Required(first, calls=Exactly(1)),
            result=Required(last, calls=Exactly(1)),
        ) -> StatusReport:
            """Read the request and return its application-owned report."""
            ...

    with pytest.raises(TimeoutError):
        asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert audits == [1]
