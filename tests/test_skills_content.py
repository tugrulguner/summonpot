"""The shipped skill is documentation; these guard what it must keep saying.

Each assertion pins a rule the framework enforces at registration. If the framework
changes, the skill has to change with it, and this test is what forces that.
"""

from __future__ import annotations

import re

import pytest

from summonpot.skills.content import SKILL_DESCRIPTION, SKILL_NAME, skill_body


def test_skill_ships_inside_the_package():
    assert skill_body().strip()
    assert SKILL_NAME == "summonpot"


def test_description_says_when_to_load_it():
    """An agent reads only the description when deciding to open the skill."""
    assert "@summon" in SKILL_DESCRIPTION
    assert len(SKILL_DESCRIPTION) < 500


@pytest.mark.parametrize(
    "rule",
    [
        "Use `...`",  # complete declaration syntax, not an abstract implementation
        "docstring",  # required, and it is the goal
        "start with `/`",  # path validation
        "(path, method)",  # duplicate-route rule
        "TYPE_CHECKING",  # unresolvable annotations are rejected
        "unbound method",  # capability must be bound
        "stream=True",  # not implemented, raises
        "query-string",  # bodyless methods
        "{customer_id}",  # path parameters bind from the URL
        "excluded from the generated request body model",  # one value, one place
        "call it with nothing but the path",  # a path-only body route needs no body
        "SUMMONPOT_MODEL=test",  # keyless trial
        "worker thread",  # thread-affine resources
        "usage_limits",  # bounding a call
    ],
)
def test_skill_documents_an_enforced_rule(rule):
    assert rule in skill_body()


@pytest.mark.parametrize("status", ["422", "429", "502", "504"])
def test_skill_documents_the_failure_statuses(status):
    assert status in skill_body()


@pytest.mark.parametrize(
    "contract_term",
    [
        "Operation(",
        "FromRequest",
        "FromResult",
        "FromContext",
        "AgentChoice",
        "output=",
        "after=",
        "reject only provable incompatibility",
    ],
)
def test_skill_documents_typed_operation_contracts(contract_term):
    assert contract_term in skill_body()


def test_skill_states_the_current_binding_execution_boundary():
    body = " ".join(skill_body().split())

    assert "one required typed operation" in body
    assert "calls=Exactly(1)" in body
    assert "trusted and defaulted arguments are hidden from the model" in body
    assert "Multi-operation chains" in body
    assert "model-supplied argument behavior" in body
    assert "executes it directly without resolving or constructing a model" in body
    assert "no model fallback after direct execution begins" in body.lower()
    assert "uses a Pydantic request model" in body
    assert "Scalar request declarations also remain agent-backed" in body
    assert "copy hooks are not proof of immutability" in body


def test_skill_uses_the_current_ai_api_positioning_and_direct_runtime_boundary():
    body = " ".join(skill_body().split())

    assert "modernizes APIs for AI" in body
    assert "stable public abstraction" in body
    assert "exact application behavior" in body
    assert "explicitly bounded agentic decisions" in body
    assert "one fully resolved `exactly(1)` operation path" in body.lower()
    assert (
        "all other declarations still use the provider-neutral agent runtime"
        in body.lower()
    )
    assert "Broader multi-operation deterministic execution remains planned" in body


def test_skill_documents_supported_request_declaration_shapes():
    body = " ".join(skill_body().split())
    body_lower = body.lower()

    assert "body-carrying methods" in body_lower
    assert "individual body parameters" in body_lower
    assert "exactly one Pydantic request model" in body
    assert "bodyless methods" in body_lower
    assert "scalar or sequences-of-scalars query parameters" in body_lower


def test_skill_documents_runtime_extras_and_safe_network_exposure():
    body = " ".join(skill_body().split())

    assert 'pip install "summonpot[serve,cli,anthropic]"' in body
    assert "`serve` installs FastAPI and uvicorn" in body
    assert "`cli` installs the `summonpot` command" in body
    assert "provider extra installs that provider's client" in body
    assert '`host="127.0.0.1"` for local development' in body
    assert "authentication in front" in body
    assert "provider credit" in body


def test_skill_python_examples_compile():
    blocks = re.findall(r"```python\n(.*?)```", skill_body(), re.DOTALL)

    assert len(blocks) >= 4
    for index, block in enumerate(blocks, 1):
        compile(block, f"summonpot-skill:{index}", "exec")


@pytest.mark.parametrize(
    "rejection",
    [
        "a placeholder that no parameter is named after",
        "the same placeholder named twice",
        "a path parameter with a default",
        "a path parameter annotated with a non-scalar",
    ],
)
def test_skill_documents_the_path_parameter_rejections(rejection):
    """Each is a registration-time error the framework raises; the skill must say so."""
    assert rejection in skill_body()


def test_skill_names_every_supported_path_scalar():
    """The accepted set is closed, so an agent must be told all of it."""
    body = skill_body()
    section = body[body.index("## Path parameters") : body.index("## Running it")]
    for scalar in ("`str`", "`int`", "`float`", "`bool`", "`UUID`"):
        assert scalar in section
