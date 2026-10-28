"""Keep the public contract documentation's authenticated-context boundary durable."""

from pathlib import Path

import pytest

import summonpot.contracts as contracts
from summonpot.skills.content import SKILL_DESCRIPTION

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "ROADMAP.md",
        "CONTRIBUTING.md",
        "src/summonpot/AGENTS.md",
        "docs/declarative-capabilities.md",
        "examples/README.md",
        "examples/13_authenticated_context/README.md",
        "src/summonpot/templates/skills/summonpot.md",
        "website/src/content/docs/architecture.mdx",
        "website/src/content/docs/capabilities.mdx",
        "website/src/content/docs/tasks/direct-execution.mdx",
        "website/src/content/docs/internals/execution.mdx",
        "website/src/content/docs/reference/operations.mdx",
    ],
)
def test_context_release_boundary_reaches_every_current_surface(relative):
    text = " ".join((ROOT / relative).read_text().split())
    assert "FromContext" in text and "0.13.0" in text, relative
    assert "feature is unreleased" not in text, relative
    assert "unreleased source" not in text, relative


def test_roadmap_has_a_distinct_013_boundary():
    assert (
        "### 0.13.0 boundary: authenticated application context"
        in (ROOT / "ROADMAP.md").read_text()
    )


def test_installed_skill_activation_mentions_authenticated_context():
    assert "authenticated FromContext" in SKILL_DESCRIPTION


def test_public_contract_docs_state_authenticated_context_version():
    text = " ".join((contracts.__doc__ or "").split())
    assert "authenticated context injection is supported from version 0.13.0" in text
    assert "supported in unreleased source" not in text
