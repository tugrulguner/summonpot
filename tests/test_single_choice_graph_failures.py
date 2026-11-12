"""Failure finalization for the newly admitted graph, using the real kernel."""

import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot._execution import _REGISTERED_PLANS
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    value: int


class Item(BaseModel):
    value: int


class Result(BaseModel):
    total: int


def build_graph(events, *, left_hook=None, timeout=None):
    def left(value: int) -> Item:
        events.append("left")
        if left_hook is not None:
            left_hook()
        return Item(value=value)

    left_op = Operation(left, bind={"value": FromRequest("value")})

    def candidates(value: int) -> list[Item]:
        events.append("candidates")
        return [Item(value=value + 1)]

    producer = Operation(candidates, bind={"value": FromRequest("value")})

    def choose(item: Item) -> Item:
        events.append("choose")
        return item

    consumer = Operation(choose, bind={"item": AgentChoice(from_result=producer)})

    def finish(a: int, b: int) -> Result:
        events.append("finish")
        return Result(total=a + b)

    terminal = Operation(
        finish,
        bind={"a": FromResult(left_op, "value"), "b": FromResult(consumer, "value")},
    )
    app = Summon(
        "failure-graph", runtime=Runtime(model="invalid:not-used", timeout=timeout)
    )

    @app("/run")
    def endpoint(
        request: Request,
        a=Required(left_op, calls=Exactly(1)),
        b=Required(producer, calls=Exactly(1)),
        c=Required(consumer, calls=Exactly(1)),
        d=Required(terminal, calls=Exactly(1)),
    ) -> Result:
        """Return the canonical joined application result."""
        ...

    return app


def test_late_sync_effect_cannot_publish_or_start_later_branches(tmp_path):
    events = []
    release = threading.Event()
    completed = threading.Event()
    effect = tmp_path / "effect.txt"

    def write_then_wait():
        effect.write_text("committed before timeout")
        assert release.wait(2), "parent escape timer failed"
        completed.set()

    app = build_graph(events, left_hook=write_then_wait, timeout=0.04)
    timer = threading.Timer(0.15, release.set)
    timer.start()
    try:
        with TestClient(build_app(app)) as client:
            response = client.post("/run", json={"value": 5})
        assert response.status_code == 504
        assert completed.wait(2)
        assert effect.read_text() == "committed before timeout"
        assert events == ["left"]
    finally:
        release.set()
        timer.join(2)


def test_application_failure_redacts_and_stops_graph():
    events = []

    def fail():
        raise RuntimeError("private-application-detail")

    app = build_graph(events, left_hook=fail)
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"value": 5})
    assert response.status_code == 500
    assert "private-application-detail" not in response.text
    assert events == ["left"]


@pytest.mark.parametrize("timeout,status", [(0.05, 504), (1.0, 200)])
def test_final_real_audit_is_inside_the_runtime_deadline(monkeypatch, timeout, status):
    events = []
    app = build_graph(events, timeout=timeout)
    plan = app._runtime._plan_for(app.endpoints[0])
    real_auditor = plan.output_auditor
    assert real_auditor is not None
    audited = []

    def slow_audit(value):
        result = real_auditor(value)
        audited.append(True)
        time.sleep(0.1)
        return result

    instrumented = replace(plan, output_auditor=slow_audit)
    key = id(app.endpoints[0])
    # Install one authoritative test-instrumented plan for transport AND runtime.
    # Replacing only Runtime._plan_for tests a mismatched transport snapshot.
    monkeypatch.setitem(
        _REGISTERED_PLANS, key, (_REGISTERED_PLANS[key][0], instrumented)
    )
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"value": 5})
    assert response.status_code == status
    assert audited == [True]
    assert events == ["left", "candidates", "choose", "finish"]
    if status == 200:
        assert response.json() == {"total": 11}


def test_final_auditor_rejection_uses_redacted_output_boundary(monkeypatch):
    events = []
    app = build_graph(events)
    plan = app._runtime._plan_for(app.endpoints[0])
    real_auditor = plan.output_auditor
    assert real_auditor is not None

    def reject(value):
        real_auditor(value)
        raise ValueError("private-final-audit-detail")

    key = id(app.endpoints[0])
    instrumented = replace(plan, output_auditor=reject)
    monkeypatch.setitem(
        _REGISTERED_PLANS, key, (_REGISTERED_PLANS[key][0], instrumented)
    )
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"value": 5})
    assert response.status_code == 502
    assert "private-final-audit-detail" not in response.text
    assert events == ["left", "candidates", "choose", "finish"]
