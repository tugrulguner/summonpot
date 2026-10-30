from pathlib import Path

ROOT = Path(__file__).parents[1]


def section(text: str, start: str, end: str) -> str:
    assert start in text
    tail = text.split(start, 1)[1]
    assert end in tail
    return tail.split(end, 1)[0]


def test_readme_execution_summary_states_narrow_versioned_exception() -> None:
    text = (ROOT / "README.md").read_text()
    summary = section(text, "> [!IMPORTANT]", "## Why summonpot?")
    assert "included from version 0.14.0" in summary
    assert "Pydantic request" in summary and "FromRequest" in summary
    assert "singleton" in summary and "multiple candidates" in summary
    assert "current source (unreleased)" in summary.lower()
    assert "one or more" in summary
    assert (
        "historical v0.14.0 remains exactly-one-choice" in summary.lower()
        and "included from version 0.14.0" in summary
    )
    assert "historical v0.14.0 remains exactly-one-choice" in summary.lower()

    table = section(
        text, "| Contract state | Current execution |", "Broader graph execution"
    )
    assert "Historical v0.13.0 behavior remains agent-mediated" in table
    assert "Included from version 0.14.0" in table
    assert "exactly one choice" in table
    assert "multi-candidate" in table


def test_roadmap_and_detail_preserve_published_boundary_and_effect_timing() -> None:
    roadmap = (ROOT / "ROADMAP.md").read_text()
    milestone = section(
        roadmap, "### 2. Result-dependent execution", "### 3. Bounded orchestration"
    )
    for expected in (
        "included from version 0.14.0",
        "published v0.13.0",
        "exactly one producer-backed choice",
        "no other choice",
        "128-candidate",
        "65,536-character",
        "provider-configuration failure",
        "all other admitted declarations keep their existing agent-mediated route",
    ):
        assert expected in milestone

    guide = (ROOT / "docs/declarative-capabilities.md").read_text()
    execution = guide.split("From 0.12.0, fully resolved chains run model-free", 1)[
        1
    ].split("## What the boundary does and does not cover", 1)[0]
    assert "published v0.13.0" in execution
    assert "0.14.0" in execution
    assert "singleton" in execution and "multiple candidates" in execution
    assert "no rollback" in execution
    current_source = section(
        guide,
        "## Current source: framework-owned decision progression",
        "## Deterministic and agentic execution",
    )
    for expected in (
        "one or more",
        "before selecting or starting that consumer",
        "no business-function tools",
        "per-binding caps",
        "remain request-local",
    ):
        assert expected in current_source


def test_current_source_multiple_choice_roadmap_is_partial_and_explicit() -> None:
    roadmap = (ROOT / "ROADMAP.md").read_text()
    source = section(
        roadmap, "## Current source, not yet released", "## Next milestones"
    )
    for expected in (
        "partial milestone 3 implementation",
        "one or more",
        "before selecting or starting that consumer",
        "framework-owned progression continues locally",
        "per binding",
        "provider-configuration failure",
        "allow_direct=False",
    ):
        assert expected in source
    milestone = section(
        roadmap,
        "### 3. Bounded orchestration",
        "### 4. Broader private",
    )
    assert "partially implemented, not complete" in milestone
    assert "finite repeated calls" in milestone


def test_example_index_and_runnable_example_describe_behavior_not_results() -> None:
    index = (ROOT / "examples/README.md").read_text()
    boundary = index.split("From 0.12.0, fully resolved chains run without a model", 1)[
        1
    ].split("## Progression", 1)[0]
    for expected in (
        "Published v0.13.0",
        "0.14.0",
        "singleton",
        "multiple candidates",
        "128 candidates and 65,536 evidence characters",
    ):
        assert expected in boundary

    example = (ROOT / "examples/12_producer_choice/README.md").read_text()
    execution = section(example, "## Execution boundary", "## Run")
    for expected in (
        "Published v0.13.0",
        "0.14.0",
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
        "Included from version 0.14.0",
        "exactly one producer-backed choice",
        "Pydantic request",
        "FromRequest",
        "singleton",
        "multiple candidates",
        "128-candidate/65,536-character",
        "provider-configuration failure",
    ):
        assert expected.lower() in opening
    assert "historical v0.14.0 remains exactly-one-choice" in opening


def test_changelog_release_section_contains_consumed_fragment() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    release = section(changelog, "## [0.14.0]", "## [0.13.0]")
    assert "result-dependent execution" in release.lower()
    fragments = [
        p
        for p in (ROOT / "changelog.d").iterdir()
        if p.is_file() and p.name != "README.md"
    ]
    assert len(fragments) == 2
    assert any(p.name == "+framework-owned-progression.added.md" for p in fragments)
    assert all(p.read_text().strip() for p in fragments)
