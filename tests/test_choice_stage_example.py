"""Runtime acceptance for the supplier choice-before-repeated-stage example."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime, _ChoiceUnavailableError

EXAMPLE = Path(__file__).parents[1] / "examples" / "17_choice_stage" / "app.py"


def load_app(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "choice_stage_example_under_test", EXAMPLE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "choice-stage.sqlite3")
    module.initialize_database()
    return module


def model_for_supplier(identifier: str, checks=("stock", "prices")) -> FunctionModel:
    """Select actual producer evidence, then request both mandatory checks."""
    repeated_calls = 0

    def respond(messages, info):
        nonlocal repeated_calls
        assert info.function_tools == []
        output = info.output_tools[0]
        props = output.parameters_json_schema["properties"]
        if "decision" in props:
            repeated_calls += 1
            if repeated_calls <= len(checks):
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            output.name,
                            {
                                "decision": "invoke",
                                "argument_0": checks[repeated_calls - 1],
                            },
                        )
                    ]
                )
            return ModelResponse(
                parts=[ToolCallPart(output.name, {"decision": "finish"})]
            )

        prompt = "\n".join(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        evidence = json.loads(prompt.splitlines()[-1])
        domain = evidence["decision_slot_0"]["candidates"]
        assert {item["value"]["price_cents"] for item in domain} == {825, 975}
        slot = next(iter(props))
        assert slot == "decision_slot_0"
        candidate = next(
            item for item in domain if item["value"]["identifier"] == identifier
        )
        return ModelResponse(
            parts=[ToolCallPart(output.name, {slot: candidate["token"]})]
        )

    return FunctionModel(respond)


def test_selected_supplier_owns_checks_verification_and_persisted_report(
    monkeypatch, tmp_path: Path
) -> None:
    module = load_app(monkeypatch, tmp_path)
    for supplier_id, review_id in (("S-101", "review-101"), ("S-202", "review-202")):
        module.summon._runtime = Runtime(
            model=model_for_supplier(supplier_id), retries=0
        )
        endpoint = module.summon.endpoints[0]
        assert [tool.fn.__name__ for tool in endpoint.tools] == [
            "find_suppliers",
            "prepare_supplier",
            "inspect_supplier",
            "verify_review",
            "persist_report",
        ]
        result = asyncio.run(
            module.summon._runtime.call(
                endpoint, {"category": "paper", "review_id": review_id}
            )
        )
        assert isinstance(result, module.ReviewReport)
        assert result.supplier_id == supplier_id
        assert {check.supplier_id for check in result.checks} == {supplier_id}
        assert {check.check for check in result.checks} == {"stock", "prices"}
        assert result.approved is (supplier_id == "S-101")
        with sqlite3.connect(module.DB_PATH) as db:
            rows = db.execute(
                "SELECT supplier_id, check_name, passed FROM review_checks "
                "WHERE review_id = ? ORDER BY supplier_id, check_name",
                (review_id,),
            ).fetchall()
            stored = db.execute(
                "SELECT report_json FROM review_reports WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        assert rows == [
            (supplier_id, "prices", int(supplier_id == "S-101")),
            (supplier_id, "stock", int(supplier_id == "S-101")),
        ]
        assert stored is not None
        assert json.loads(stored[0]) == result.model_dump(mode="json")

    with sqlite3.connect(module.DB_PATH) as db:
        all_checks = db.execute(
            "SELECT DISTINCT supplier_id FROM review_checks ORDER BY supplier_id"
        ).fetchall()
    assert all_checks == [("S-101",), ("S-202",)]


def test_singleton_candidate_skips_selection_but_runs_check_stage(
    monkeypatch, tmp_path
):
    module = load_app(monkeypatch, tmp_path)
    calls = []
    base_model = model_for_supplier("S-303")
    base_respond = base_model.function
    assert base_respond is not None

    def respond(messages, info):
        calls.append(info.output_tools[0].parameters_json_schema["properties"])
        return base_respond(messages, info)

    module.summon._runtime = Runtime(model=FunctionModel(respond), retries=0)
    result = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0],
            {"category": "office", "review_id": "singleton-review"},
        )
    )
    assert result.supplier_id == "S-303"
    assert result.approved
    assert len(calls) == 3
    assert all("decision" in schema for schema in calls)


def test_zero_candidates_do_not_write_reports_or_checks(monkeypatch, tmp_path: Path):
    module = load_app(monkeypatch, tmp_path)
    calls = []

    def no_tools(messages, info):
        calls.append(info)
        raise AssertionError("No model turn is expected for an empty candidate set")

    module.summon._runtime = Runtime(model=FunctionModel(no_tools), retries=0)
    with pytest.raises(_ChoiceUnavailableError):
        asyncio.run(
            module.summon._runtime.call(
                module.summon.endpoints[0],
                {"category": "missing", "review_id": "empty-review"},
            )
        )
    assert calls == []
    with sqlite3.connect(module.DB_PATH) as db:
        assert db.execute("SELECT COUNT(*) FROM review_checks").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM review_reports").fetchone()[0] == 0


def test_early_finish_persists_a_denied_review(monkeypatch, tmp_path):
    module = load_app(monkeypatch, tmp_path)
    module.summon._runtime = Runtime(
        model=model_for_supplier("S-101", ("stock",)), retries=0
    )
    result = asyncio.run(
        module.summon._runtime.call(
            module.summon.endpoints[0], {"category": "paper", "review_id": "partial"}
        )
    )
    assert result.approved is False
    assert [item.check for item in result.checks] == ["stock"]
    with sqlite3.connect(module.DB_PATH) as db:
        stored = db.execute(
            "SELECT report_json FROM review_reports WHERE review_id='partial'"
        ).fetchone()
    assert json.loads(stored[0]) == result.model_dump(mode="json")
