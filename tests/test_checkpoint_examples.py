"""Runnable examples exercise actual framework progression and SQLite readback."""

import asyncio
import importlib.util
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime

ROOT = Path(__file__).parents[1]


def load_example(number, name, variable, database, monkeypatch):
    monkeypatch.setenv(variable, str(database))
    path = ROOT / "examples" / f"{number}_{name}" / "app.py"
    module_name = f"checkpoint_example_{number}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def fixture_runtime(turns):
    def model(messages, info):
        assert not info.function_tools
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        assert isinstance(text, str)
        envelope = json.loads(text[text.index('{"decision_slot_') :])
        choice = {
            slot: domain["candidates"][0]["token"] for slot, domain in envelope.items()
        }
        turns.append(choice)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, choice)])

    return Runtime(model=FunctionModel(model), retries=0)


@pytest.mark.parametrize(
    "record_id,status,effects,model_calls",
    [
        ("valid", "verified", 0, 0),
        ("needs-review", "verified", 2, 1),
        ("exhausted", "unresolved", 2, 2),
    ],
)
def test_cleanup_actual_effects_and_canonical_report(
    tmp_path, monkeypatch, record_id, status, effects, model_calls
):
    path = tmp_path / "cleanup.sqlite"
    module = load_example(
        "18", "checkpoint_cleanup", "CHECKPOINT_CLEANUP_DB", path, monkeypatch
    )
    turns = []
    module.app._runtime = fixture_runtime(turns)
    result = asyncio.run(
        module.app._runtime.call(module.app.endpoints[0], {"record_id": record_id})
    )
    assert result.status == status and len(turns) == model_calls
    with sqlite3.connect(path) as db:
        saved = json.loads(
            db.execute(
                "SELECT report_json FROM reports WHERE record_id=?", (record_id,)
            ).fetchone()[0]
        )
        actions = db.execute(
            "SELECT revision,action FROM corrections WHERE record_id=? ORDER BY revision",
            (record_id,),
        ).fetchall()
        untouched = db.execute(
            "SELECT count(*) FROM corrections WHERE record_id!=?", (record_id,)
        ).fetchone()[0]
        revision, name, sku, email = db.execute(
            "SELECT revision,name,sku,email FROM records WHERE record_id=?",
            (record_id,),
        ).fetchone()
    assert saved == result.model_dump(mode="json")
    assert len(actions) == effects == revision == result.revision and untouched == 0
    assert (name == name.strip() and sku == sku.upper() and email == email.lower()) == (
        status == "verified"
    )
    if effects:
        assert [action for _, action in actions] == ["trim_name", "uppercase_sku"]


@pytest.mark.parametrize(
    "job_id,status,effects,model_calls",
    [
        ("complete", "verified", 0, 0),
        ("pending", "verified", 2, 2),
        ("exhausted", "unresolved", 2, 2),
    ],
)
def test_status_actual_effects_and_canonical_report(
    tmp_path, monkeypatch, job_id, status, effects, model_calls
):
    path = tmp_path / "status.sqlite"
    module = load_example(
        "19", "checkpoint_status", "CHECKPOINT_STATUS_DB", path, monkeypatch
    )
    turns = []
    module.app._runtime = fixture_runtime(turns)
    result = asyncio.run(
        module.app._runtime.call(module.app.endpoints[0], {"job_id": job_id})
    )
    assert result.status == status and len(turns) == model_calls
    with sqlite3.connect(path) as db:
        saved = json.loads(
            db.execute(
                "SELECT report_json FROM reports WHERE job_id=?", (job_id,)
            ).fetchone()[0]
        )
        count = db.execute(
            "SELECT count(*) FROM refreshes WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        revision, completed, target = db.execute(
            "SELECT revision,completed,target FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        untouched = db.execute(
            "SELECT count(*) FROM refreshes WHERE job_id!=?", (job_id,)
        ).fetchone()[0]
    assert saved == result.model_dump(mode="json")
    assert count == effects == revision == result.revision and untouched == 0
    assert completed == result.completed and target == result.target
    assert (completed >= target) == (status == "verified")
