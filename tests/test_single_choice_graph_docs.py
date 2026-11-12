"""Static contract regressions for the unreleased single-choice DAG slice."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _section(path: str, heading: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return " ".join(text[start:] if end < 0 else text[start:end].split())


def _choice_contract(text: str) -> None:
    lower = text.lower()
    assert "unreleased" in lower or "current source" in lower
    assert "exactly one" in lower and "producer-backed" in lower and "choice" in lower
    assert "required `exactly(1)`" in lower
    assert "acyclic" in lower and "unique sink" in lower
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
    assert "no business" in lower and "final model acknowledgment" in lower
    assert "empty" in lower and "409" in lower
    assert "no global choice barrier" in lower
    assert (
        "tool_calls_limit" in lower or "function-tool quota" in lower
    ) and "allow_direct=false" in lower
    assert "linear" in lower and (
        "multiple choices" in lower or "multiple-choice" in lower
    )
    assert "not a public graph api" in lower
    assert "parallel" in lower and "feedback" in lower and "recovery" in lower


def test_readme_adds_unreleased_choice_dag_after_historical_boundaries():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    historical = text.index("## Version 0.15.0 branch/join execution")
    heading = "## Unreleased source: one producer-backed choice in required DAGs"
    new = text.index(heading)
    following = text.index("## Version 0.15.0 bounded checkpoint progression", new)
    assert historical < new < following
    assert (
        "historical version 0.15.0 branch/join execution remains choice-free"
        in text[new:following].lower()
    )
    _choice_contract(text[new:following])


def test_roadmap_records_narrow_slice_without_completing_milestones():
    text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    heading = "## Unreleased source: one producer-backed choice in required DAGs"
    start = text.index(heading)
    section = text[
        start : text.index("\nThe version 0.15.0 repeated-stage extension", start)
    ]
    _choice_contract(section)
    assert "milestones 3 and 4 remain partial" in section.lower()


def test_examples_index_links_parent_owned_example_path():
    text = (ROOT / "examples/README.md").read_text(encoding="utf-8")
    start = text.index("### 23. ")
    section = text[start : text.find("\n### ", start + 5)]
    assert "23_choice_branch_join/README.md" in section
    assert "unreleased" in section.lower() and "singleton" in section.lower()
    assert "opaque-token" in section.lower() and "not in published" in section.lower()


def test_packaged_skill_and_content_regression_teach_new_boundary():
    text = (ROOT / "src/summonpot/templates/skills/summonpot.md").read_text(
        encoding="utf-8"
    )
    heading = "## Unreleased source: one producer-backed choice in required DAGs"
    start = text.index(heading)
    section = text[start : text.find("\n## ", start + len(heading))]
    _choice_contract(section)
    assert "historical v0.15.0 branch/join" in section.lower()
    content = (ROOT / "src/summonpot/skills/content.py").read_text(encoding="utf-8")
    assert "single-choice required DAGs" in content


def test_website_reference_and_architecture_align_with_source_boundary():
    heading = "## Unreleased source: one producer-backed choice in required DAGs"
    for path in (
        "website/src/content/docs/reference/operations.mdx",
        "website/src/content/docs/architecture.mdx",
    ):
        text = (ROOT / path).read_text(encoding="utf-8")
        start = text.index(heading)
        section = text[start : text.find("\n## ", start + len(heading))]
        _choice_contract(section)
    reference = (ROOT / "website/src/content/docs/reference/operations.mdx").read_text(
        encoding="utf-8"
    )
    historical = reference[reference.index("## Version 0.15.0 branch/join execution") :]
    historical = historical[: historical.find("\n## ", 4)]
    assert "`AgentChoice` is excluded" in historical
    assert "published v0.14.0 is unchanged" in historical.lower()
