"""Current-source chain eligibility must not be inferred from global keywords."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_canonical_stage_chain_contract_preserves_complete_predicate():
    text = (ROOT / "docs/stage-chains.added.md").read_text()
    for phrase in (
        "across the whole chain",
        "required `Exactly(1)`",
        "nonterminal",
        "positive finite",
        "immutable closure record",
        "exact full response annotation",
        "before authentication",
        "no boundary reset",
    ):
        assert phrase.lower() in text.lower()
    assert 'invocation="final"' in text
    assert "Published v0.14.0 is unchanged" in text
    assert "Existing examples 1-15 are unchanged" in text


def test_each_current_source_summary_explains_chain_wide_request_binding():
    paths = [ROOT / "README.md", ROOT / "src/summonpot/templates/skills/summonpot.md"]
    paths += [
        ROOT / "website/src/content/docs" / path
        for path in (
            "index.mdx",
            "architecture.mdx",
            "capabilities.mdx",
            "internals/execution.mdx",
            "reference/operations.mdx",
            "tasks/agent-choice.mdx",
            "tasks/direct-execution.mdx",
        )
    ]
    for path in paths:
        text = path.read_text()
        assert "across the whole chain" in text
        assert (
            "nonterminal" in text
            and "resolved prefix" in text
            and "resolved suffix" in text
        )
        assert "before one lazy model resolution" in text
        assert "stage-chains.added.md" in text


def test_new_example_is_separate_and_old_contract_retains_compatibility_note():
    index = (ROOT / "examples/README.md").read_text()
    assert "16_stage_chain/" in index and "15_repeated_stage/" in index
    previous = (ROOT / "docs/repeated-stage-results.added.md").read_text()
    assert "original two-operation admission form" in previous
    assert "stage-chains.added.md" in previous
