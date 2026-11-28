"""The current multi-choice source contract must be discoverable independently."""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HEADING = "## Unreleased source: multiple producer-backed choices in required DAGs"


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "ROADMAP.md",
        "docs/declarative-capabilities.md",
        "src/summonpot/templates/skills/summonpot.md",
        "website/src/content/docs/architecture.mdx",
        "website/src/content/docs/reference/operations.mdx",
        "website/src/content/docs/tasks/agent-choice.mdx",
    ],
)
def test_current_multiple_choice_contract(path):
    text = (ROOT / path).read_text()
    start = text.index(HEADING)
    end = text.find("\n## ", start + len(HEADING))
    section = " ".join(
        text[start:].split() if end < 0 else text[start:end].split()
    ).lower()
    for term in [
        "unreleased",
        "one or more",
        "producer-backed",
        "exactly(1)",
        "fromrequest",
        "single sink",
        "sequential",
        "same consumer",
        "distinct consumers",
        "singleton",
        "opaque",
        "shared",
        "quota",
        "allow_direct=false",
        "linear",
        "0.15.0",
    ]:
        assert term in section, (path, term)
    assert "24_multiple_choice_branch_join" in section


def test_new_example_is_discoverable_in_both_indexes():
    for path in ["README.md", "examples/README.md"]:
        assert "24_multiple_choice_branch_join/" in (ROOT / path).read_text()
