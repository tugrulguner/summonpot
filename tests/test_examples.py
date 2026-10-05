"""Acceptance coverage for the executable example progression."""

import asyncio
import importlib.metadata
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

ROOT = Path(__file__).resolve().parent.parent


EXAMPLES = [
    ("basic_app.py", "/review", "post"),
    ("02_required_capability.py", "/quotes", "post"),
    ("03_agentic_order.py", "/orders", "post"),
    ("04_http_methods.py", "/products", "get"),
    ("04_http_methods.py", "/products", "post"),
    ("05_bounded_runtime.py", "/summaries", "post"),
    ("06_support_service/app.py", "/support", "post"),
    ("07_bound_operation.py", "/customers/view", "post"),
    ("08_direct_execution.py", "/quotes/direct", "post"),
    ("09_contract_boundaries/app.py", "/customers/view", "post"),
]


def _load_example(relative_path: str, monkeypatch):
    example = ROOT / "examples" / relative_path
    monkeypatch.syspath_prepend(str(example.parent))
    return runpy.run_path(str(example), run_name=f"example_{relative_path}")["summon"]


@pytest.mark.parametrize(("relative_path", "route", "method"), EXAMPLES)
def test_every_example_builds_its_advertised_openapi_route(
    relative_path, route, method, monkeypatch
):
    summon = _load_example(relative_path, monkeypatch)

    schema = build_app(summon).openapi()

    assert method in schema["paths"][route]


def test_example_entrypoint_inventory_is_complete():
    discovered = {
        path.relative_to(ROOT / "examples").as_posix()
        for path in (ROOT / "examples").rglob("*.py")
        if path.parent == ROOT / "examples" or path.name == "app.py"
    }
    expected = {relative_path for relative_path, _, _ in EXAMPLES}

    assert discovered == expected


def test_minimal_example_serves_a_real_keyless_request(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")
    summon = _load_example("basic_app.py", monkeypatch)

    response = TestClient(build_app(summon)).post(
        "/review", json={"text": "The contract is concise and clear."}
    )

    assert response.status_code == 200
    assert set(response.json()) == {"sentiment", "summary"}


def test_bound_operation_example_runs_through_real_http(monkeypatch):
    summon = _load_example("07_bound_operation.py", monkeypatch)
    turns = 0

    def model_function(messages, info: AgentInfo):
        nonlocal turns
        turns += 1
        if turns == 1:
            tool = info.function_tools[0]
            assert tool.name == "load_customer"
            assert sorted(tool.parameters_json_schema["properties"]) == ["format"]
            return ModelResponse(
                parts=[ToolCallPart("load_customer", {"format": "summary"})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "customer_id": "customer-7",
                        "display": "Ada — active",
                    },
                )
            ]
        )

    summon._runtime = Runtime(model=FunctionModel(model_function))
    response = TestClient(build_app(summon)).post(
        "/customers/view", json={"customer_id": "customer-7"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "customer_id": "customer-7",
        "display": "Ada — active",
    }


def test_direct_example_runs_without_resolving_a_model(monkeypatch):
    monkeypatch.setenv("SUMMONPOT_MODEL", "invalid-provider:no-model")
    summon = _load_example("08_direct_execution.py", monkeypatch)

    response = TestClient(build_app(summon)).post(
        "/quotes/direct",
        json={
            "unit_price_cents": 1299,
            "quantity": 3,
            "tax_rate_percent": "8.25",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "subtotal_cents": 3897,
        "tax_cents": 322,
        "total_cents": 4219,
    }
    assert summon._runtime._agents == {}


def test_curated_direct_demo_rejects_invalid_request_without_running_operation(
    monkeypatch,
):
    monkeypatch.setenv("SUMMONPOT_MODEL", "invalid-provider:no-model")
    summon = _load_example("08_direct_execution.py", monkeypatch)

    response = TestClient(build_app(summon)).post(
        "/quotes/direct",
        json={"unit_price_cents": 1299, "quantity": 0, "tax_rate_percent": "8.25"},
    )

    assert response.status_code == 422
    assert summon._runtime._agents == {}


def test_contract_boundary_example_runs_all_release_checks(monkeypatch):
    checks = ROOT / "examples" / "09_contract_boundaries" / "checks.py"
    monkeypatch.syspath_prepend(str(checks.parent))
    run_checks = runpy.run_path(str(checks), run_name="contract_boundary_checks")[
        "run_checks"
    ]

    assert asyncio.run(run_checks()) == {
        "fail_closed_registration": True,
        "receiving_constraint": True,
        "output_namespace": True,
        "raw_http_parity": True,
    }


def test_support_example_uses_only_admitted_legacy_capabilities(monkeypatch):
    summon = _load_example("06_support_service/app.py", monkeypatch)
    tools = {tool.name: tool for tool in summon.endpoints[0].tools}

    assert set(tools) == {"load_customer", "load_policy", "create_ticket"}
    assert all(tool.contract is None for tool in tools.values())
    assert all(tool.required is True for tool in tools.values())


def test_support_example_guide_states_the_current_binding_boundary():
    guide = " ".join((ROOT / "examples/README.md").read_text(encoding="utf-8").split())

    assert "FromRequest" in guide
    assert "FromResult" in guide
    assert "AgentChoice" in guide
    assert "rejected at registration" in guide
    assert "filtered model schema" in guide
    assert "one permitted start" in guide
    assert "08_direct_execution.py" in guide
    assert "requires no provider model or credentials" in guide
    assert "09_contract_boundaries" in guide
    assert "fail-closed registration" in guide
    assert "receiving-operation constraints" in guide
    assert "output namespaces" in guide
    assert "raw runtime and HTTP" in guide
    assert (
        "current `@summon` requests still use the configured model runtime" not in guide
    )
    assert (
        "Automatic no-model deterministic endpoint execution is planned, not shipped."
        not in guide
    )


def test_readme_teaches_the_current_api_without_version_specific_migration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Migrating from the 0.5 API" not in readme
    assert "from summonpot import Pot" not in readme
    assert "from summonpot import Summon" in readme
    assert 'summon = Summon("review-api")' in readme
    assert '@summon("/review")' in readme


def test_examples_use_one_documented_provider_installation():
    guide = (ROOT / "examples/README.md").read_text(encoding="utf-8")
    bounded = (ROOT / "examples/05_bounded_runtime.py").read_text(encoding="utf-8")

    assert "summonpot[serve,cli,openrouter]" in guide
    assert 'model="openrouter:openai/gpt-4o-mini"' in bounded
    assert "OPENAI_API_KEY" not in guide


def test_examples_are_in_static_quality_gates():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "ruff check src/ tests/ examples/ scripts/" in makefile
    assert "ruff format --check src/ tests/ examples/ scripts/" in makefile
    assert "pyright src/ tests/ examples/ scripts/" in makefile
    assert "ruff check src/ tests/ examples/ scripts/" in workflow
    assert "ruff format --check src/ tests/ examples/ scripts/" in workflow
    assert 'include = ["src", "tests", "examples", "scripts"]' in project


def test_cli_launches_every_example_through_real_http():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "release_smoke.py"),
            "--examples-root",
            str(ROOT / "examples"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "verified 9 example applications" in result.stdout


def test_release_smoke_verifies_installed_cli_version():
    namespace = runpy.run_path(
        str(ROOT / "scripts/release_smoke.py"), run_name="release_smoke"
    )

    assert namespace["_verify_installed_version"]() == importlib.metadata.version(
        "summonpot"
    )


def test_release_smoke_removes_pythonpath_from_child_processes(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    namespace = runpy.run_path(
        str(ROOT / "scripts/release_smoke.py"), run_name="release_smoke"
    )

    environment = namespace["_smoke_environment"](SUMMONPOT_MODEL="test")

    assert "PYTHONPATH" not in environment
    assert environment["SUMMONPOT_MODEL"] == "test"


def test_ci_smokes_examples_against_the_installed_wheel():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert '"${wheel}[serve,cli]"' in workflow
    assert "scripts/release_smoke.py" in workflow
    assert "env -u PYTHONPATH" in workflow
    assert "--examples-root examples" in workflow


def test_ci_and_release_verify_runnable_sdist_assets():
    for workflow_name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        assert '/scripts/release_smoke.py"' in workflow
        assert '/examples/09_contract_boundaries/app.py"' in workflow
        assert '"/.venv" not in name' in workflow


def test_playground_teaches_the_shipped_bounded_operation_contract():
    page = (ROOT / "website/src/pages/playground.astro").read_text(encoding="utf-8")
    home = (ROOT / "website/src/content/docs/index.mdx").read_text(encoding="utf-8")
    example = (ROOT / "examples/07_bound_operation.py").read_text(encoding="utf-8")

    assert "examples/07_bound_operation.py" in page
    assert (
        "resolve(process.cwd(), '../examples/07_bound_operation.py')" in page
        or "new URL('../../../examples/07_bound_operation.py', import.meta.url)" in page
    )
    assert "code={contract}" in page and "code={example}" in page
    assert "example.slice(example.indexOf('customer_lookup = Operation(')" in page
    for token in (
        'FromRequest("customer_id")',
        "AgentChoice()",
        "Required(customer_lookup, calls=Exactly(1))",
        "output=CustomerRecord",
    ):
        assert token in example
    assert 'name="customer_id" type="text"' in page
    assert "customer-7" in page and "customer-9" in page
    assert "Run contract" in page
    assert "No model, server, network call, arbitrary code" in page
    assert "browser preview" in page and "No agent or Python server runs." in page
    assert "operation override cannot replace request-owned data" in page
    assert '"customer-7": {"name": "Ada", "status": "active"}' in example
    assert '"customer-9": {"name": "Grace", "status": "paused"}' in example
    assert "/playground/" in home
    assert not (ROOT / "website/src/components/AgentDemo.astro").exists()
