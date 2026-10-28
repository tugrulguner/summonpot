from pathlib import Path

ROOT = Path(__file__).parents[1]


def section(text: str, start: str, end: str) -> str:
    assert start in text
    tail = text.split(start, 1)[1]
    assert end in tail
    return tail.split(end, 1)[0]


def test_readme_execution_summary_states_narrow_unreleased_exception() -> None:
    text = (ROOT / "README.md").read_text()
    summary = section(text, "> [!IMPORTANT]", "## Why summonpot?")
    assert "unreleased" in summary
    assert "Pydantic request" in summary and "FromRequest" in summary
    assert "singleton" in summary and "two-or-more" in summary
    assert "published v0.13.0 behavior" in summary and "unreleased" in summary
    assert "remain agent-mediated except for the narrow unreleased" in summary

    table = section(
        text, "| Contract state | Current execution |", "Broader graph execution"
    )
    assert "Published v0.13.0: agent-mediated" in table
    assert "Current unreleased source" in table
    assert "exactly one choice" in table
    assert "multi-candidate" in table


def test_roadmap_and_detail_preserve_published_boundary_and_effect_timing() -> None:
    roadmap = (ROOT / "ROADMAP.md").read_text()
    milestone = section(
        roadmap, "### 2. Result-dependent execution", "### 3. Bounded orchestration"
    )
    for expected in (
        "unreleased",
        "published v0.13.0",
        "exactly one producer-backed choice",
        "no other choice",
        "128-candidate",
        "65,536-character",
        "provider-configuration failure",
        "existing agent-mediated execution",
    ):
        assert expected in milestone

    guide = (ROOT / "docs/declarative-capabilities.md").read_text()
    execution = section(guide, "## Deterministic and agentic execution", "## ")
    assert "published v0.13.0" in execution
    assert "unreleased" in execution
    assert "singleton" in execution and "multiple candidates" in execution
    assert "no rollback" in execution


def test_example_index_and_runnable_example_describe_behavior_not_results() -> None:
    index = (ROOT / "examples/README.md").read_text()
    boundary = section(index, "From 0.12.0, fully resolved chains", "## ")
    for expected in (
        "published v0.13.0",
        "unreleased",
        "singleton",
        "multiple candidates",
        "128-item/65,536-character",
    ):
        assert expected in boundary

    example = (ROOT / "examples/12_producer_choice/README.md").read_text()
    execution = section(example, "## Execution boundary", "## Run")
    for expected in (
        "Published v0.13.0",
        "unreleased",
        "exactly one",
        "singleton",
        "Two or more",
        "128",
        "65,536",
        "no rollback",
    ):
        assert expected in execution
    assert "produced" not in execution.lower()


def test_packaged_skill_opening_teaches_current_narrow_route_with_historical_caveat() -> (
    None
):
    skill = (ROOT / "src/summonpot/templates/skills/summonpot.md").read_text()
    opening = section(skill, "summonpot modernizes", "## The endpoint shape").lower()
    for expected in (
        "published v0.13.0",
        "unreleased",
        "exactly one producer-backed choice",
        "Pydantic request",
        "FromRequest",
        "singleton",
        "two or more candidates",
        "128-item/65,536-character",
        "provider-configuration failure",
    ):
        assert expected.lower() in opening
    assert "other producer choices keep their existing agent route" in opening


def test_changelog_fragment_has_valid_orphan_name_and_added_section() -> None:
    fragments = list((ROOT / "changelog.d").glob("*result-dependent-execution*.md"))
    assert len(fragments) == 1
    assert fragments[0].name.endswith(".added.md")
    assert fragments[0].stem.split("+", 1)[-1]
    assert "result-dependent" in fragments[0].read_text().lower()
