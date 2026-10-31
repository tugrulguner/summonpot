from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repeated_stage_contract_is_narrow_and_source_only() -> None:
    contract = (ROOT / "docs/repeated-stage-results.added.md").read_text()
    for required in (
        'invocation="final"',
        "successful invocation",
        "immutable closure record",
        "producer identity",
        "invocation ordinal",
        "canonical validated output",
        "not ready merely because the producer met its minimum",
        "no fallback to an earlier invocation",
        "Published v0.14.0 is unchanged",
        "inspect/correct/verify workflow",
    ):
        assert required.lower() in contract.lower()
    for unsupported in (
        "arbitrary ordinal",
        "aggregation",
        "repeated consumers",
        "multiple repeated operations",
        "general graphs",
        "cycles",
        "parallelism",
        "durable resumption",
        "rollback",
    ):
        assert unsupported.lower() in contract.lower()


def test_index_and_docs_expose_one_new_example_without_rewriting_existing_guides() -> (
    None
):
    index = (ROOT / "examples/README.md").read_text()
    assert "### 15. Repeated-stage final-result consumer" in index
    assert "15_repeated_stage/" in index
    assert "repeated-result addressing in chains remains next" not in index

    for relative in (
        "README.md",
        "ROADMAP.md",
        "docs/declarative-capabilities.md",
        "src/summonpot/templates/skills/summonpot.md",
    ):
        text = (ROOT / relative).read_text()
        assert "repeated-stage-results.added.md" in text or relative == "ROADMAP.md"


def test_website_summaries_no_longer_claim_all_repeated_result_chains_planned() -> None:
    paths = (
        "index.mdx",
        "architecture.mdx",
        "capabilities.mdx",
        "internals/execution.mdx",
        "reference/operations.mdx",
        "tasks/direct-execution.mdx",
        "tasks/agent-choice.mdx",
    )
    for relative in paths:
        text = (ROOT / "website/src/content/docs" / relative).read_text().lower()
        assert 'invocation="final"' in text
        assert "published v0.14.0" in text
        assert "repeated-result addressing in chains remains next" not in text
        assert "inspect/correct/verify" in text


def test_packaged_skill_python_fences_compile() -> None:
    text = (ROOT / "src/summonpot/templates/skills/summonpot.md").read_text()
    blocks = re.findall(r"```python\s*\n(.*?)```", text, flags=re.DOTALL)
    assert blocks
    for index, block in enumerate(blocks):
        compile(block, f"summonpot-skill-block-{index}", "exec")
