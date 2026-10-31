from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_all_seven_web_surfaces_identify_the_narrow_unreleased_shape():
    paths = [
        "index.mdx",
        "architecture.mdx",
        "capabilities.mdx",
        "internals/execution.mdx",
        "reference/operations.mdx",
        "tasks/direct-execution.mdx",
        "tasks/agent-choice.mdx",
    ]
    for rel in paths:
        text = (ROOT / "website/src/content/docs" / rel).read_text().lower()
        assert "bounded repeated calls" in text
        assert "unreleased" in text and "1 <= minimum <= maximum" in text
        assert "maximum > 1" in text and "literal[str]" in text
        assert "final successful canonical" in text
        assert "tool_calls_limit" in text
        assert "repeated-result addressing" in text


def test_canonical_contract_and_packaged_skill_preserve_eligibility_and_limits():
    contract = (ROOT / "docs/bounded-repeated-calls.added.md").read_text()
    skill = (ROOT / "src/summonpot/templates/skills/summonpot.md").read_text()
    for text in (contract, skill):
        for phrase in (
            "Pydantic request",
            "at least one `FromRequest`",
            "Literal[str]",
            "65,536 characters per",
            "tool_calls_limit",
            "v0.14.0",
            "repeated-result addressing",
        ):
            assert phrase.lower() in text.lower()
        assert (
            "no implicit principal" in text
            or "principal/full ledger are not implicitly exposed" in text
        )
        assert "aggregate prompt budget" in text
    assert "before provider resolution" in skill.lower()
    assert "before provider resolution" in contract.lower()


def test_readme_and_examples_index_bound_new_source_and_name_example_14():
    readme = (ROOT / "README.md").read_text().lower()
    index = (ROOT / "examples/README.md").read_text().lower()
    for text in (readme, index):
        assert "bounded repeated calls" in text or "bounded repeated audit" in text
        assert "published v0.14.0" in text or "historical v0.14.0" in text
        assert "milestone 3" in text and "partial" in text
    assert "14. bounded repeated calls: audit" in index


def test_no_scope_expansion_in_new_contract():
    text = (ROOT / "docs/bounded-repeated-calls.added.md").read_text().lower()
    for excluded in (
        "no `fromresult`",
        "no `after`",
        "no `depends`",
        "no implicit batch",
        "zero minimum",
        "unbounded shape",
        "no general graph",
    ):
        assert excluded in text
