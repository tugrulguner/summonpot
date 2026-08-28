"""Presentation guards for the repository's primary adoption surface."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def _normalize(text: str) -> str:
    return " ".join(text.replace("\n>", "\n").lower().split())


def test_readme_preserves_signature_hero_and_unified_framework_value():
    readme = README.read_text(encoding="utf-8")
    introduction = readme.split("## Why summonpot?", 1)[0]
    normalized_introduction = _normalize(introduction)

    assert '<img src="summonpot.png" alt="Summonpot" width="600">' in introduction
    assert (
        "declare deterministic operations and agentic decisions through one endpoint"
        in normalized_introduction
    )
    assert (
        "combining application-owned execution and model-owned choices in one typed http api"
        in normalized_introduction
    )
    assert "both flow through the same http route" in normalized_introduction
    assert "request/response contract" in normalized_introduction
    assert "openapi" in normalized_introduction


def test_readme_states_the_current_runtime_boundary_before_positioning():
    readme = README.read_text(encoding="utf-8")
    introduction = _normalize(readme.split("## Why summonpot?", 1)[0])

    assert (
        "every current production `@summon` request runs through the configured model"
        in introduction
    )
    assert (
        "deterministic operations still execute as exact application code inside that runtime"
        in introduction
    )
    assert (
        "automatic no-model execution for contracts with one fully resolved operation path "
        "is on the [roadmap](roadmap.md), not shipped behavior" in introduction
    )


def test_readme_explains_both_flows_under_one_endpoint_contract():
    readme = README.read_text(encoding="utf-8")
    why = readme.split("## Why summonpot?", 1)[1].split("That declaration answers", 1)[
        0
    ]
    declaration = why.split("```python", 1)[1].split("```", 1)[0]
    section = readme.split("### One endpoint, both flows", 1)[1].split(
        "## What ships today", 1
    )[0]
    normalized_section = _normalize(section)

    assert "def build_report(" in declaration
    assert "# Deterministic:" in declaration
    assert '"topic": FromRequest("topic")' in declaration
    assert "# Agentic:" in declaration
    assert '"format": AgentChoice()' in declaration
    assert '@summon("/research")' in declaration
    assert "calls=Exactly(1)" in declaration
    assert "the example above combines both kinds of work" in normalized_section
    assert (
        "request, response, route, and openapi contract remain one declaration"
        in normalized_section
    )
    assert "the configured model participates in every request" in normalized_section
    assert (
        "automatic no-model execution for a fully resolved declaration remains planned"
        in normalized_section
    )


def test_readme_replaces_the_text_formula_with_a_visual_flow_diagram():
    readme = README.read_text(encoding="utf-8")
    introduction = readme.split("## Why summonpot?", 1)[0]
    diagram = ROOT / "docs" / "assets" / "authority-boundary.svg"

    assert 'src="docs/assets/authority-boundary.svg"' in introduction
    assert "typed request model\n+ fixed goal" not in introduction
    assert diagram.is_file()

    content = diagram.read_text(encoding="utf-8")
    assert (
        "One Summonpot declaration combines deterministic work and agentic choice"
        in content
    )
    assert "TYPED REQUEST" in content
    assert "DETERMINISTIC" in content
    assert "FromRequest(&quot;topic&quot;)" not in content
    assert 'FromRequest("topic")' in content
    assert "AGENTIC" in content
    assert "AgentChoice()" in content
    assert "Required(..., calls=Exactly(1))" in content
    assert "TYPED RESPONSE" in content


def test_readme_keeps_the_established_structure_without_version_history():
    readme = README.read_text(encoding="utf-8")

    assert "### New in " not in readme
    assert "## Migrating from the " not in readme
    assert "Summonpot 0.6.0" not in readme
    assert "Summonpot 0.5.0" not in readme
    assert 'pip install "summonpot[serve,cli]"' in readme
    assert "git+https://github.com/tugrulguner/summonpot.git@" not in readme


def test_readme_distinguishes_tool_schema_hiding_from_prompt_secrecy():
    readme = _normalize(README.read_text(encoding="utf-8"))

    assert "tool-schema hiding is not prompt secrecy" in readme
    assert "other operation shapes remain on the legacy model-supplied path" in readme


def test_readme_links_the_permanent_modepot_discord_from_hero_and_community():
    readme = README.read_text(encoding="utf-8")
    introduction = readme.split("## Why summonpot?", 1)[0]
    community = readme.split("## Community", 1)[1].split("## Contributing", 1)[0]
    invite = "https://discord.gg/u3AANZr6RG"

    assert readme.count(invite) == 2
    assert invite in introduction
    assert "Join the ModePot Discord" in introduction
    assert '<a href="#community">Community</a>' in introduction
    assert invite in community
    assert "shared community for" in community
    assert "Use GitHub issues for reproducible bugs" in community
