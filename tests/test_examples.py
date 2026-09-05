"""Acceptance coverage for the executable example progression."""

import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from summonpot import AgentChoice, Exactly, FromRequest, FromResult
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


def test_support_example_declares_the_typed_operation_chain(monkeypatch):
    summon = _load_example("06_support_service/app.py", monkeypatch)
    tools = {tool.name: tool for tool in summon.endpoints[0].tools}

    customer = tools["load_customer"]
    policy = tools["load_policy"]
    ticket = tools["create_ticket"]

    assert customer.contract.bind == {"customer_id": FromRequest("customer_id")}
    assert policy.contract.bind == {"topic": AgentChoice()}
    assert ticket.contract.bind == {
        "customer_id": FromResult(customer.contract, "customer_id"),
        "priority": AgentChoice(),
        "summary": AgentChoice(),
    }
    assert ticket.contract.after == (customer.contract, policy.contract)
    assert ticket.bounds == Exactly(1)
    assert customer.required is True
    assert policy.required is True
    assert ticket.required is True


def test_support_example_guide_states_the_current_binding_boundary():
    guide = (ROOT / "examples/README.md").read_text(encoding="utf-8")

    assert "FromRequest" in guide
    assert "FromResult" in guide
    assert "AgentChoice" in guide
    assert "does not inject bound values" in guide
    assert "filtered model schema" in guide
    assert "one permitted start" in guide
    assert "08_direct_execution.py" in guide
    assert "requires no provider model or credentials" in guide
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
