"""Cross-surface regression checks for the narrow branch/join contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return " ".join((ROOT / path).read_text(encoding="utf-8").split())


def test_readme_roadmap_and_example_index_scope_branch_join():
    readme = _text("README.md")
    roadmap = _text("ROADMAP.md")
    examples = _text("examples/README.md")
    assert "Version 0.15.0 branch/join execution" in readme
    assert "Published v0.14.0 is unchanged; milestone 4 is partial" in readme
    assert "examples/20_branch_join/README.md" in readme
    assert "partially implemented, not complete" in roadmap
    assert "unique sink reached by every operation" in roadmap
    assert "branch/join" in examples and "example 20" in examples.lower()


def test_packaged_skill_and_activation_description_state_contract():
    body = _text("src/summonpot/templates/skills/summonpot.md")
    activation = _text("src/summonpot/skills/content.py")
    assert "Version 0.15.0 branch/join execution" in body
    for phrase in (
        "at least one `FromRequest`",
        "unique sink",
        "declaration-order tie-breaking",
        "`AgentChoice` is not supported",
        "not a public graph API",
    ):
        assert phrase in body
    assert "branch/join graphs" in activation


def test_website_surfaces_are_aligned_without_claiming_general_graphs():
    paths = [
        "website/src/content/docs/reference/operations.mdx",
        "website/src/content/docs/internals/execution.mdx",
        "website/src/content/docs/architecture.mdx",
        "website/src/content/docs/index.mdx",
    ]
    for path in paths:
        body = _text(path)
        assert "Version 0.15.0 branch/join execution" in body
        assert "Published v0.14.0 is unchanged" in body
        assert (
            "unique sink reached by every operation" in body
            or "unique sink reached by all operations" in body
        )
        assert "not a public graph API" in body
        assert "parallel scheduler" in body


def test_capability_guide_preserves_broader_graph_deferral():
    body = _text("docs/declarative-capabilities.md")
    assert "Version 0.15.0 branch/join execution" in body
    assert "`AgentChoice` is not admitted" in body
    assert "not a public graph API or parallel scheduler" in body
    assert "milestone 4 is partial" in body
    assert (
        "`FromResult` and `after` are supported only in a sequential chain" not in body
    )
    assert "Producer-backed `AgentChoice(from_result=...)` remains restricted" in body
    reference = _text("website/src/content/docs/reference/operations.mdx")
    assert (
        "`FromResult`, `after`, and producer-backed choices work only" not in reference
    )
    assert (
        "`FromResult` and `after` also work in that fully resolved branch/join slice"
        in reference
    )
