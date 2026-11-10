"""Durable boundaries for the v0.15.0 release, independent of future fragments."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
SURFACES = (
    "README.md",
    "ROADMAP.md",
    "docs/declarative-capabilities.md",
    "examples/README.md",
    "src/summonpot/templates/skills/summonpot.md",
    "website/src/content/docs/index.mdx",
    "website/src/content/docs/reference/operations.mdx",
)


def test_release015_headings_do_not_call_included_features_unreleased():
    for filename in SURFACES:
        text = (ROOT / filename).read_text()
        assert "0.15.0" in text, filename
        for line in text.splitlines():
            if line.startswith("#") and "0.15.0" in line:
                assert "unreleased" not in line.lower(), (filename, line)


def test_release015_notes_include_all_feature_families():
    notes = (
        (ROOT / "CHANGELOG.md")
        .read_text()
        .split("## [0.15.0]", 1)[1]
        .split("\n## [", 1)[0]
    )
    for feature in (
        "branches and joins",
        "checkpoint",
        "multiple producer-backed choices",
        "repeated calls",
        "repeated stage",
        "output=",
        "CLI/HTTP",
    ):
        assert feature.lower() in notes.lower(), feature


def test_release015_foundation_includes_all_admitted_execution_families():
    text = " ".join((ROOT / "ROADMAP.md").read_text().split())
    foundation = text.split("## Shipped foundation", 1)[1].split(
        "### 0.5.0 boundary", 1
    )[0]
    for feature in ("bounded repetition", "checkpoint", "branch/join"):
        assert feature in foundation
    assert "exact built-in source vocabulary" in foundation
    assert "Adding another capability cannot downgrade" in foundation
    assert (
        "supported single-operation or uniquely ordered sequential required"
        not in foundation
    )


def test_release015_boundary_sentences_have_a_subject():
    import re

    for filename in (*SURFACES, "docs/reviewing.md"):
        text = (ROOT / filename).read_text()
        assert not re.search(
            r"Included from version 0\.15\.0 (?:also )?(?:supports|includes|adds|permits|admits)\b",
            text,
        ), filename
