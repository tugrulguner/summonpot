"""Runtime and SQLite acceptance for the repeated-stage example."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime

EXAMPLE = Path(__file__).parents[1] / "examples" / "15_repeated_stage" / "app.py"


def load_app(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "repeated_stage_example_under_test", EXAMPLE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "audit.sqlite3")
    module.initialize_database()
    return module


@pytest.mark.parametrize("checks", [["stock", "prices"], ["stock", "stock", "prices"]])
def test_repeated_stage_closes_then_persists_canonical_final_report(
    monkeypatch, tmp_path, checks
):
    module = load_app(monkeypatch, tmp_path)
    decisions = iter(
        [{"decision": "invoke", "argument_0": check} for check in checks]
        + ([{"decision": "finish"}] if len(checks) < 3 else [])
    )
    decision_count = 0

    def model(messages, info):
        nonlocal decision_count
        decision_count += 1
        assert info.function_tools == []
        assert len(info.output_tools) == 1
        schema = info.output_tools[0].parameters_json_schema
        assert set(schema["properties"]) == {"decision", "argument_0"}
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(decisions))]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(
            module.summon.endpoints[0], {"audit_id": "audit-test-1"}
        )
    )

    assert (
        decision_count == 3
    )  # maximum closes automatically, without a finish acknowledgment
    assert isinstance(result, module.AuditReport)
    assert result.audit_id == "audit-test-1"
    assert result.checks == ["prices", "stock"]
    assert result.finding_count == 2
    assert [finding.check for finding in result.findings] == ["prices", "stock"]

    with module.connect() as db:
        check_rows = db.execute(
            "SELECT check_name, anomaly_count, details_json FROM audit_checks "
            "WHERE audit_id = ? ORDER BY check_name",
            ("audit-test-1",),
        ).fetchall()
        reports = db.execute(
            "SELECT report_json FROM audit_reports WHERE audit_id = ?",
            ("audit-test-1",),
        ).fetchall()
    assert len(check_rows) == 2  # repeated stock invocation did not duplicate its row
    assert [row["check_name"] for row in check_rows] == ["prices", "stock"]
    assert len(reports) == 1
    assert json.loads(reports[0]["report_json"]) == result.model_dump(mode="json")
    assert result.findings[0].details == [
        "MUG-1: listed price differs from approved price"
    ]
    assert result.findings[1].details == ["MUG-1: stock count differs"]
