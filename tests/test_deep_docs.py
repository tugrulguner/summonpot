"""Regression checks for the deep documentation's runnable contracts."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

from fastapi.testclient import TestClient

from summonpot import Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "website/src/content/docs"


def _example(relative: str) -> tuple[str, Summon]:
    text = (DOCS / relative).read_text(encoding="utf-8")
    match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    assert match is not None, f"No complete Python example in {relative}"
    source = match.group(1)
    ast.parse(source)
    module_name = f"summonpot_documented_{Path(relative).stem}"
    module = ModuleType(module_name)
    module.__file__ = str(DOCS / relative)
    sys.modules[module_name] = module
    exec(compile(source, relative, "exec", dont_inherit=True), module.__dict__)
    return source, cast(Summon, module.__dict__["summon"])


def test_deep_documentation_python_examples_compile():
    sources = (
        "tasks/direct-execution.mdx",
        "tasks/agent-choice.mdx",
        "reference/operations.mdx",
        "internals/execution.mdx",
        "guides/operations.mdx",
    )
    for relative in sources:
        text = (DOCS / relative).read_text(encoding="utf-8")
        for index, match in enumerate(
            re.finditer(r"```python\n(.*?)```", text, re.DOTALL)
        ):
            ast.parse(match.group(1), filename=f"{relative} example {index + 1}")


def test_documented_model_free_example_runs_over_http_and_rejects_bad_input():
    _, summon = _example("tasks/direct-execution.mdx")
    assert hasattr(summon, "_runtime")
    summon._runtime = Runtime(model="invalid-provider:no-model")
    client = TestClient(build_app(summon))

    response = client.post(
        "/quotes/direct",
        json={
            "unit_price_cents": 1299,
            "quantity": 3,
            "tax_rate_percent": "8.25",
        },
    )
    invalid = client.post(
        "/quotes/direct",
        json={
            "unit_price_cents": 1299,
            "quantity": 0,
            "tax_rate_percent": "8.25",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "subtotal_cents": 3897,
        "tax_cents": 322,
        "total_cents": 4219,
    }
    assert invalid.status_code == 422
    assert summon._runtime._agents == {}


def test_documented_agent_choice_example_runs_only_the_keyless_test_model():
    _, summon = _example("tasks/agent-choice.mdx")
    summon._runtime = Runtime(model="test")

    response = TestClient(build_app(summon)).post(
        "/summarize",
        json={
            "topic": "A concise contract separates trusted request data from bounded choices."
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == {"summary", "style"}
    assert summon._runtime._agents


def test_documentation_routes_cover_the_public_contract_and_planned_boundary():
    reference = (DOCS / "reference/operations.mdx").read_text(encoding="utf-8")
    internals = (DOCS / "internals/execution.mdx").read_text(encoding="utf-8")
    agent = (DOCS / "tasks/agent-choice.mdx").read_text(encoding="utf-8")
    for token in (
        "FromRequest",
        "AgentChoice",
        "Required",
        "Exactly(1)",
        "FromResult",
        "FromContext",
        "after",
        "Bare callable",
        "registration",
        "authorization",
        "keyless",
        "not a dry-run sandbox",
    ):
        assert token.lower() in reference.lower() or token.lower() in agent.lower()
    for token in (
        "registration",
        "request",
        "operation",
        "provider",
        "HTTP",
        "output",
        "permitted start is not successful completion",
        "planned",
    ):
        assert token.lower() in internals.lower()


def test_short_quick_start_links_the_deeper_guides():
    quick_start = (DOCS / "quick-start.mdx").read_text(encoding="utf-8")
    assert "pip install" in quick_start
    assert "/build/direct-execution/" in quick_start
    assert "/build/agent-choice/" in quick_start
    assert "/reference/operations/" in quick_start
