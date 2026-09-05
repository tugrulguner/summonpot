"""Keep request provenance and output-constructor limits in shipped guidance."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_custom_output_initializers_are_documented_as_registration_errors():
    for path in (
        ROOT / "docs/declarative-capabilities.md",
        ROOT / "src/summonpot/templates/skills/summonpot.md",
    ):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "__init__" in text
        assert "nested models" in text
        assert "registration" in text.lower()
        assert "model validators" in text


def test_request_validation_provenance_is_documented_in_packaged_skill():
    text = (ROOT / "src/summonpot/templates/skills/summonpot.md").read_text(
        encoding="utf-8"
    )
    assert "HTTP request validation runs once" in text
    assert "plan-bound validated" in text
    assert "ordinary request wrappers are not trusted" in text
