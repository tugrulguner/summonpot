"""Final checkpoint output rejection uses the established HTTP output boundary."""

from typing import Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, StrictBool

import summonpot._execution as execution
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
from summonpot.runtime import Runtime
from summonpot.server import build_app


class AuditRequest(BaseModel):
    key: str


class Checked(BaseModel):
    key: str
    accepted: StrictBool


class Receipt(BaseModel):
    revision: int


class AuditedReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    accepted: bool


def application(checkpoint):
    starts = []

    def read(key: str) -> Checked:
        starts.append("read")
        return Checked(key=key, accepted=True)

    def change(key: str, mode: Literal["go"]) -> Receipt:
        starts.append("change")
        return Receipt(revision=1)

    def finish(key: str, accepted: bool) -> AuditedReport:
        starts.append("finish")
        return AuditedReport(key=key, accepted=accepted)

    checked = Operation(read, bind={"key": FromRequest("key")}, output=Checked)
    changed = Operation(
        change,
        bind={"key": FromResult(checked, "key"), "mode": AgentChoice()},
        output=Receipt,
    )
    report = Operation(
        finish,
        bind={
            name: FromResult(checked, name, invocation="final" if checkpoint else None)
            for name in ("key", "accepted")
        },
        output=AuditedReport,
    )
    app = Summon("audit-failure", runtime=Runtime(model="invalid:no-provider"))
    if checkpoint:

        @app("/run")
        def endpoint(
            request: AuditRequest,
            check=Required(checked, calls=Between(1, 2), until="accepted"),
            step=Depends(changed, calls=AtMost(1)),
            final=Required(report, calls=Exactly(1)),
        ) -> AuditedReport:
            """Check and return a canonical application report."""
            ...

    else:

        @app("/run")
        def endpoint(
            request: AuditRequest,
            check=Required(checked, calls=Exactly(1)),
            final=Required(report, calls=Exactly(1)),
        ) -> AuditedReport:
            """Read and return a canonical application report."""
            ...

    return app, starts


@pytest.mark.parametrize(
    "checkpoint", [False, True], ids=["resolved-chain", "checkpoint"]
)
def test_final_namespace_failure_maps_to_output_error(monkeypatch, checkpoint):
    compile_auditor = execution._compile_output_auditor
    audited = []

    def compile_observed(adapter):
        audit = compile_auditor(adapter)

        def mutate_before_audit(value):
            # Exercise the real post-validation auditor rather than raising a
            # fabricated exception. No invalid value may reach HTTP serialization.
            object.__setattr__(
                value, "__pydantic_extra__", {"accepted": "PRIVATE_MARKER"}
            )
            audited.append(1)
            return audit(value)

        return mutate_before_audit

    monkeypatch.setattr(execution, "_compile_output_auditor", compile_observed)
    app, starts = application(checkpoint)
    with TestClient(build_app(app), raise_server_exceptions=False) as client:
        response = client.post("/run", json={"key": "A"})
    assert audited == [1] and starts == ["read", "finish"]
    assert "PRIVATE_MARKER" not in response.text
    assert response.status_code == 502
