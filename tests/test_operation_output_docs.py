from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/declarative-capabilities.md",
        "src/summonpot/templates/skills/summonpot.md",
        "website/src/content/docs/reference/operations.mdx",
    ],
)
def test_output_completion_docs_preserve_explicit_inputs_and_release_boundary(path):
    text = " ".join((ROOT / path).read_text().split())
    assert "unreleased" in text
    assert "Annotated" in text
    assert "bindings are never inferred" in text
    assert "v0.14.0" in text
