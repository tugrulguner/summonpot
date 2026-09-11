"""Executable checks for the README's security guidance.

Security guidance must not point users at protection that does not exist, so the
mitigation snippet is executed rather than merely read.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"
ROOT = README.parent
ROADMAP = ROOT / "ROADMAP.md"
CHANGELOG = ROOT / "CHANGELOG.md"
CAPABILITY_GUIDE = ROOT / "docs" / "declarative-capabilities.md"
REVIEWING = ROOT / "docs" / "reviewing.md"


def _snippet_after(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    assert heading in text, f"README no longer contains {heading!r}"
    block = text.split(heading, 1)[1]
    match = re.search(r"```python\n(.*?)```", block, re.DOTALL)
    assert match is not None, f"no Python snippet follows {heading!r}"
    return match.group(1)


def test_binding_mitigation_snippet_runs():
    """The exposure warning tells users to bound the runtime; that must be possible."""
    namespace: dict = {}

    exec(_snippet_after("Binding and exposure"), namespace)

    summon = namespace["summon"]
    assert summon._runtime.usage_limits is not None
    assert summon._runtime.timeout is not None


def test_bounding_a_call_snippet_runs():
    namespace: dict = {}

    exec(_snippet_after("## Bounding a call"), namespace)

    summon = namespace["summon"]
    assert summon._runtime.usage_limits is not None
    assert summon._runtime.timeout == 30.0


@pytest.mark.parametrize("api", ["UsageLimits"])
def test_documented_public_names_are_importable(api):
    import summonpot

    assert hasattr(summonpot, api), f"README documents summonpot.{api}"


def test_declaration_surfaces_use_ellipsis_instead_of_not_implemented():
    surfaces = [
        README,
        ROOT / "src/summonpot/summon.py",
        ROOT / "src/summonpot/contracts.py",
        ROOT / "src/summonpot/templates/skills/summonpot.md",
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("*.py")),
    ]
    stale = [
        str(path.relative_to(ROOT))
        for path in surfaces
        if re.search(
            r"^\s*raise NotImplementedError\s*$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    ]

    assert stale == []


def test_roadmap_scopes_the_enforced_authority_boundary():
    roadmap = " ".join(ROADMAP.read_text(encoding="utf-8").split())

    assert "executes directly without resolving or constructing a model" in roadmap
    assert "For the enforced single required `Exactly(1)` slice" in roadmap
    assert "leaves only declared `AgentChoice` values to the agent" in roadmap
    assert (
        "Unsupported shapes retain legacy model-supplied argument behavior" in roadmap
    )


def test_roadmap_advances_after_the_narrow_no_model_slice():
    roadmap = " ".join(ROADMAP.read_text(encoding="utf-8").split())

    shipped_direct = roadmap.index("single-operation deterministic execution")
    hardening = roadmap.index("### 1. Contract enforcement and input/output hardening")
    result_chain = roadmap.index("### 2. Validated result chains and failure semantics")
    compiler = roadmap.index("### 6. Broader deterministic execution compiler")
    database = roadmap.index("### 7. Exact database operations")

    assert shipped_direct < hardening < result_chain < compiler < database
    assert "exactly one required `Exactly(1)` operation" in roadmap
    assert "at least one `FromRequest` binding" in roadmap
    assert (
        "only `FromRequest` or immutable identity-stable callable defaults" in roadmap
    )
    assert "operation output exactly matching the endpoint response model" in roadmap
    assert "without resolving, constructing, or calling a model" in roadmap
    assert "There is no model fallback after direct execution begins" in roadmap
    assert (
        "The broader multi-operation deterministic compiler remains planned" in roadmap
    )


def test_public_docs_describe_one_permitted_start_not_exactly_once_execution():
    for path in (README, CHANGELOG, ROADMAP):
        text = path.read_text(encoding="utf-8")
        assert "exactly-once execution" not in text.lower()
        assert "bound exactly-once operations" not in text.lower()
        assert "exact-once slices" not in text.lower()

    roadmap = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    assert "required single-start slices" in roadmap

    assert "one permitted start per request" in README.read_text(encoding="utf-8")


def test_execution_overview_is_executor_neutral():
    readme = " ".join(README.read_text(encoding="utf-8").split())
    capability_guide = " ".join(CAPABILITY_GUIDE.read_text(encoding="utf-8").split())

    assert "Request data becomes validated execution input" in readme
    assert "available to execution" in capability_guide
    assert "On the agent-backed path" in capability_guide


def test_public_surfaces_document_stable_openapi_operation_ids():
    skill = ROOT / "src/summonpot/templates/skills/summonpot.md"
    for path in (README, ROADMAP, skill):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "OpenAPI `operationId`" in text
        assert "registration" in text.lower()


def test_reviewing_distinguishes_shipped_direct_execution_from_planned_work():
    reviewing = " ".join(REVIEWING.read_text(encoding="utf-8").split())

    assert "single-operation direct execution has shipped" in reviewing
    assert "Broader model-free execution" in reviewing
    assert "remains planned" in reviewing


def test_readme_states_current_python_support_without_release_candidate_language():
    readme = README.read_text(encoding="utf-8")

    assert "Python 3.11 through 3.13" in readme
    assert "This source revision" not in readme
    assert "newly built artifacts" not in readme
    assert "already-published packages" not in readme
