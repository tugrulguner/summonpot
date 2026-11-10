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
