from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_authenticated_context_docs_preserve_trust_boundary_and_release_history():
    files = [
        ROOT / "README.md",
        ROOT / "ROADMAP.md",
        ROOT / "docs/declarative-capabilities.md",
        ROOT / "website/src/content/docs/reference/operations.mdx",
        ROOT / "src/summonpot/templates/skills/summonpot.md",
    ]
    for path in files:
        text = path.read_text()
        assert "FromContext" in text
        assert "0.12.0" in text
        assert "tenant" in text.lower()
        assert "model" in text.lower()
    for path in files:
        normalized = " ".join(path.read_text().split())
        assert "included from version 0.13.0" in normalized, path
        assert "unreleased source" not in normalized.lower(), path
    skill = files[-1].read_text()
    for phrase in (
        "secrets.compare_digest",
        "frozen=True",
        'extra="forbid"',
        "included from version 0.13.0",
        "This was not part of version 0.12.0.",
        "trusted application code",
        "tenant isolation",
        "runtime timeout",
        "provider protects every declared Summon",
        "preflighted before any operation",
        "standard `Runtime.call`",
        "login",
        "authorization",
        "tenant isolation",
    ):
        assert phrase in skill


def test_no_affected_surface_calls_context_globally_unsupported():
    paths = [
        ROOT / "README.md",
        ROOT / "ROADMAP.md",
        *ROOT.joinpath("docs").rglob("*.md"),
        *ROOT.joinpath("website/src/content/docs").rglob("*.mdx"),
        ROOT / "examples/README.md",
        ROOT / "src/summonpot/templates/skills/summonpot.md",
    ]
    for path in paths:
        text = path.read_text()
        assert "FromContext remains unsupported" not in text, path
        assert "`FromContext` remains unsupported" not in text, path
        normalized = " ".join(text.split())
        assert (
            "direct unbounded chain choices, `FromContext`, broader graphs and bounds remain unsupported"
            not in normalized
        ), path
