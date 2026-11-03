"""The new composed predicate must be explicit in source-only summaries."""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "ROADMAP.md",
        "docs/declarative-capabilities.md",
        "src/summonpot/templates/skills/summonpot.md",
        *[
            "website/src/content/docs/" + p
            for p in (
                "index.mdx",
                "architecture.mdx",
                "capabilities.mdx",
                "internals/execution.mdx",
                "reference/operations.mdx",
                "tasks/agent-choice.mdx",
                "tasks/direct-execution.mdx",
            )
        ],
    ],
)
def test_composed_source_summary_has_its_complete_boundary(relative):
    text = (ROOT / relative).read_text()
    assert (
        "Current source (unreleased) also composes exactly one producer-backed choice argument"
        in text
    )
    summary = text.split(
        "Current source (unreleased) also composes exactly one producer-backed choice argument",
        1,
    )[1].split("Published v0.14.0 is unchanged.", 1)[0]
    for phrase in (
        "prefix consumer",
        "nonterminal bounded repeated stage",
        "resolved suffix",
        "list[ConcreteModel]",
        "chain-wide `FromRequest`",
        "exact terminal response ownership",
        "Singleton selection still leads to model-backed repeated decisions",
        "model-configuration lookup",
        "fresh request starts a fresh run",
    ):
        assert phrase.lower() in summary.lower(), (relative, phrase)
    assert "choice-before-stage.added.md" in text


def test_canonical_contract_distinguishes_adapter_reuse_and_request_scope():
    text = (ROOT / "docs/choice-before-stage.added.md").read_text()
    for phrase in (
        "not a guarantee",
        "SDK adapter instance",
        "fresh HTTP request",
        "before authentication",
        "Existing HTTP transport validation",
        "canonical validated output",
        "Examples 1",
    ):
        assert phrase.lower() in text.lower()
    assert 'invocation="final"' in text
    assert "v0.14.0" in text


def test_new_example_has_a_separate_index_entry():
    assert "17_choice_stage/" in (ROOT / "examples/README.md").read_text()
