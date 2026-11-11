"Regression checks for the version 0.15.0 checkpoint documentation boundary."

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_checkpoint_contract_is_consistent_across_owned_public_surfaces():
    paths = [
        "README.md",
        "ROADMAP.md",
        "docs/declarative-capabilities.md",
        "src/summonpot/templates/skills/summonpot.md",
        "website/src/content/docs/architecture.mdx",
        "website/src/content/docs/reference/operations.mdx",
        "website/src/content/docs/internals/execution.mdx",
        "website/src/content/docs/index.mdx",
    ]
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "Version 0.15.0 bounded checkpoint progression" in text
        assert 'Required(check, calls=Between(1, M), until="accepted")' in text
        assert "stored, non-null strict Boolean field" in text
        assert "Mth false closes unresolved" in text
        assert "choice domain" in text.lower()
        assert "409" in text
        assert (
            "not an unresolved report" in text
            or "not an unresolved result" in text
            or "not unresolved" in text
        )
        assert "0.15.0" in text and "v0.14.0" in text
        assert "rollback" in text.lower() and "recovery" in text.lower()


def test_roadmap_does_not_call_all_feedback_work_unimplemented():
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert "and bounded checkpoint progression" in roadmap
    assert "Broader feedback workflows" in roadmap
    assert "this slice does not implement them" not in roadmap


def test_checkpoint_examples_are_separate_and_current_source_only():
    guide = (ROOT / "examples/README.md").read_text(encoding="utf-8")
    assert "18_checkpoint_cleanup/" in guide
    assert "19_checkpoint_status/" in guide
    assert "published v0.14.0 does not support" in guide.lower()
    assert "Existing examples remain separate and unchanged" in (
        ROOT / "docs/checkpoint-progression.added.md"
    ).read_text(encoding="utf-8")
