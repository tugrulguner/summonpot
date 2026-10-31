"""Real-runtime SQLite acceptance for the bounded audit example."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime

EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "14_bounded_audit"
_spec = importlib.util.spec_from_file_location(
    "bounded_audit_example_test", EXAMPLE_DIR / "app.py"
)
assert _spec is not None and _spec.loader is not None
example = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = example
_spec.loader.exec_module(example)


def select_checks(
    checks: list[str], observations: list[dict] | None = None
) -> FunctionModel:
    proposed = iter(checks)

    def respond(messages, info):
        assert info.function_tools == []
        assert len(info.output_tools) == 1
        schema = info.output_tools[0].parameters_json_schema
        assert set(schema["properties"]) == {"decision", "argument_0"}
        assert schema["properties"]["decision"]["enum"] == ["invoke", "finish"]
        literal_branch = next(
            branch
            for branch in schema["properties"]["argument_0"]["anyOf"]
            if "enum" in branch
        )
        assert literal_branch["enum"] == [
            "stock",
            "prices",
            "deliveries",
        ]
        assert "audit_id" not in json.dumps(schema)
        choice = next(proposed, None)
        payload = (
            {"decision": "finish"}
            if choice is None
            else {
                "decision": "invoke",
                "argument_0": choice,
            }
        )
        if observations is not None:
            observations.append(payload)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    return FunctionModel(respond)


def setup(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "bounded-audit.sqlite3"
    monkeypatch.setenv("BOUNDED_AUDIT_DB", str(path))
    monkeypatch.setattr(example, "DB_PATH", path)
    example.initialize_database()
    return path


def test_two_calls_finish_with_cumulative_canonical_snapshot(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    observations: list[dict] = []
    example.summon._runtime = Runtime(
        model=select_checks(["stock", "prices"], observations)
    )

    result = asyncio.run(
        example.summon._runtime.call(
            example.summon.endpoints[0], {"audit_id": "audit-two"}
        )
    )

    assert [item["decision"] for item in observations] == ["invoke", "invoke", "finish"]
    assert result.audit_id == "audit-two"
    assert result.checks == ["prices", "stock"]
    assert [finding.anomaly_count for finding in result.findings] == [1, 1]
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT check_name, anomaly_count FROM audit_checks "
            "WHERE audit_id = ? ORDER BY check_name",
            ("audit-two",),
        ).fetchall() == [("prices", 1), ("stock", 1)]


def test_three_successes_auto_finalize_without_acknowledgment(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    observations: list[dict] = []
    example.summon._runtime = Runtime(
        model=select_checks(["stock", "prices", "deliveries"], observations)
    )

    result = asyncio.run(
        example.summon._runtime.call(
            example.summon.endpoints[0], {"audit_id": "audit-max"}
        )
    )

    assert [item["decision"] for item in observations] == ["invoke"] * 3
    assert result.checks == ["deliveries", "prices", "stock"]
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit_checks WHERE audit_id = ?", ("audit-max",)
            ).fetchone()[0]
            == 3
        )


def test_same_audit_and_check_reuses_application_owned_durable_finding(
    tmp_path, monkeypatch
):
    path = setup(tmp_path, monkeypatch)
    payload = {"audit_id": "audit-retry"}
    snapshots = []
    for _ in range(2):
        example.summon._runtime = Runtime(model=select_checks(["stock"]))
        snapshots.append(
            asyncio.run(
                example.summon._runtime.call(example.summon.endpoints[0], payload)
            )
        )

    assert snapshots[0] == snapshots[1]
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit_checks WHERE audit_id = ? AND check_name = ?",
                ("audit-retry", "stock"),
            ).fetchone()[0]
            == 1
        )
        assert db.execute(
            "SELECT anomaly_count FROM audit_checks WHERE audit_id = ? AND check_name = ?",
            ("audit-retry", "stock"),
        ).fetchone() == (1,)


def test_example_registers_expected_public_route(monkeypatch, tmp_path):
    from summonpot.server import build_app

    monkeypatch.setenv("BOUNDED_AUDIT_DB", str(tmp_path / "openapi.sqlite3"))
    schema = build_app(example.summon).openapi()

    assert "post" in schema["paths"]["/audits"]
    request_schema = schema["components"]["schemas"]["AuditRequest"]
    assert set(request_schema["properties"]) == {"audit_id"}
    assert all(
        "inspect_inventory" not in name for name in schema["paths"]["/audits"]["post"]
    )
