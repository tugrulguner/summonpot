"""Release-boundary regressions for required branch/join execution."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
HEADING = "## Version 0.16.0: producer-backed choices in required DAGs"


def _section(path: str, heading: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return " ".join((text[start:] if end < 0 else text[start:end]).split())


def _choice_contract(text: str) -> None:
    lower = text.lower()
    assert "version 0.16.0 admits" in lower and "one or more producer-backed" in lower
    assert "required `exactly(1)`" in lower
    assert "acyclic" in lower and "single sink reached by every operation" in lower
    assert "at least one `fromrequest`" in lower
    assert "exact full" in lower and "response annotation" in lower
    assert (
        "declaration order" in lower
        or "declaration priorit" in lower
        or "declaration-priority" in lower
    ) and "sequential" in lower
    assert "singleton" in lower and (
        "no model" in lower or "without model lookup" in lower
    )
    assert "ambiguous" in lower and "opaque" in lower
    assert "no business" in lower and "model-authored terminal response" in lower
    assert "empty" in lower and "409" in lower
    assert "no global choice barrier" in lower
    assert (
        "tool_calls_limit" in lower or "function-tool quota" in lower
    ) and "allow_direct=false" in lower
    assert "existing linear compatibility remains unchanged" in lower
    assert "no public graph api" in lower
    assert "parallel" in lower and "feedback" in lower and "recovery" in lower


def test_readme_adds_versioned_choice_dag_after_historical_boundaries():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    historical = text.index("## Version 0.15.0 branch/join execution")
    new = text.index(HEADING)
    following = text.index("## Version 0.15.0 bounded checkpoint progression", new)
    assert historical < new < following
    assert (
        "version 0.15.0 branch/join execution remains choice-free"
        in text[new:following].lower()
    )
    _choice_contract(text[new:following])


def test_roadmap_records_narrow_slice_without_completing_milestones():
    section = _section("ROADMAP.md", HEADING)
    _choice_contract(section)
    assert "milestones 3 and 4 remain partial" in section.lower()


def test_examples_index_links_parent_owned_example_path():
    text = (ROOT / "examples/README.md").read_text(encoding="utf-8")
    start = text.index("### 23. ")
    section = text[start : text.find("\n### ", start + 5)]
    assert "23_choice_branch_join/README.md" in section
    assert "included from version 0.16.0" in section.lower()
    assert "singleton" in section.lower() and "opaque-token" in section.lower()
    assert "version 0.15.0 branch/join execution remains choice-free" in section.lower()
    for path in (
        "examples/23_choice_branch_join/README.md",
        "examples/23_choice_branch_join/app.py",
        "examples/24_multiple_choice_branch_join/README.md",
        "examples/24_multiple_choice_branch_join/app.py",
    ):
        material = (ROOT / path).read_text(encoding="utf-8").lower()
        assert "requires summonpot 0.16.0 or later" in material
        assert "unreleased" not in material


def test_packaged_skill_and_content_regression_teach_new_boundary():
    path = "src/summonpot/templates/skills/summonpot.md"
    text = (ROOT / path).read_text(encoding="utf-8")
    section = _section(path, HEADING)
    _choice_contract(section)
    assert "version 0.15.0 branch/join execution remains choice-free" in section.lower()
    assert "from 0.16.0, in the required-dag contract" in text.lower()
    content = (ROOT / "src/summonpot/skills/content.py").read_text(encoding="utf-8")
    assert "producer-backed choices in required branch/join contracts" in content


def test_website_reference_and_architecture_align_with_source_boundary():
    for path in (
        "website/src/content/docs/reference/operations.mdx",
        "website/src/content/docs/architecture.mdx",
    ):
        _choice_contract(_section(path, HEADING))
    reference = (ROOT / "website/src/content/docs/reference/operations.mdx").read_text(
        encoding="utf-8"
    )
    historical = reference[reference.index("## Version 0.15.0 branch/join execution") :]
    historical = historical[: historical.find("\n## ", 4)]
    assert "`AgentChoice` is excluded" in historical
    assert "published v0.14.0 is unchanged" in historical.lower()
