"""Presentation guards for the repository's primary adoption surface."""

import struct
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
        "declare deterministic operations and agentic decisions through one framework"
        in normalized_introduction
    )
    assert (
        "combining application-owned execution and agent-owned choices in one typed http api"
        in normalized_introduction
    )
    assert "summonpot modernizes apis for ai" in normalized_introduction
    assert (
        "deterministic and agentic endpoints use the same declaration style"
        in normalized_introduction
    )
    assert (
        "marks the exact arguments where the agent may decide"
        in normalized_introduction
    )
    assert "bounded agent loop" in normalized_introduction
    assert "model-owned" not in normalized_introduction
    assert "request/response validation" in normalized_introduction
    assert "openapi" in normalized_introduction


def test_readme_states_the_current_runtime_boundary_before_positioning():
    readme = README.read_text(encoding="utf-8")
    introduction = _normalize(readme.split("## Why summonpot?", 1)[0])

    assert (
        "one fully resolved `exactly(1)` operation path now executes directly without "
        "resolving or constructing a model" in introduction
    )
    assert (
        "all other declarations still use summonpot's provider-neutral agent runtime"
        in introduction
    )
    assert "within the runtime-enforced binding slice" in introduction
    assert "unsupported legacy binding shapes may remain model-supplied" in introduction
    assert (
        "broader multi-operation deterministic execution remains on the "
        "[roadmap](roadmap.md)" in introduction
    )


def test_readme_shows_deterministic_and_agentic_endpoints_in_one_code_block():
    readme = README.read_text(encoding="utf-8")
    why = readme.split("## Why summonpot?", 1)[1].split("Those declarations answer", 1)[
        0
    ]
    declaration = why.split("```python", 1)[1].split("```", 1)[0]
    deterministic_path = declaration.split("def build_deterministic_report", 1)[
        1
    ].split("def build_agentic_report", 1)[0]
    agentic_path = declaration.split("def build_agentic_report", 1)[1]
    section = readme.split("### One declaration style, both endpoint flows", 1)[
        1
    ].split("## What ships today", 1)[0]
    normalized_section = _normalize(section)

    assert "deterministic_report_operation = Operation(" in deterministic_path
    assert 'bind={"topic": FromRequest("topic")}' in deterministic_path
    assert "AgentChoice()" not in deterministic_path
    assert '"format": AgentChoice()' in agentic_path
    assert '@summon("/reports/deterministic")' in declaration
    assert '@summon("/reports/agentic")' in declaration
    assert declaration.count("calls=Exactly(1)") == 2
    assert (
        "`/reports/deterministic` binds every operation argument to validated application data"
        in normalized_section
    )
    assert (
        "`/reports/agentic` uses the same declaration style but adds one explicit "
        "`agentchoice()`" in normalized_section
    )
    assert (
        "the fully resolved endpoint executes once without constructing a model"
        in normalized_section
    )
    assert (
        "the endpoint with `agentchoice()` still uses the agent runtime"
        in normalized_section
    )
    assert "model-owned operation choice" not in normalized_section


def test_readme_replaces_the_text_formula_with_a_png_flow_diagram():
    readme = README.read_text(encoding="utf-8")
    introduction = readme.split("## Why summonpot?", 1)[0]
    diagram = ROOT / "docs" / "assets" / "one-declaration-two-flows.png"
    source = ROOT / "docs" / "assets" / "authority-boundary.svg"
    packaged_image = (
        "https://raw.githubusercontent.com/tugrulguner/summonpot/"
        "a3238041b53f6f07d4575ecfae5a77f60a551500/"
        "docs/assets/one-declaration-two-flows.png"
    )

    assert f'src="{packaged_image}"' in introduction
    assert 'src="docs/assets/one-declaration-two-flows.png"' not in introduction
    assert "typed request model\n+ fixed goal" not in introduction
    assert diagram.is_file()
    data = diagram.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (1440, 560)

    content = source.read_text(encoding="utf-8")
    assert (
        "One Summonpot framework supports deterministic and agentic endpoints"
        in content
    )
    assert "SUMMON APP" in content
    assert "same declaration style" in content
    assert "SHIPPED SINGLE-OP DIRECT SLICE" in content
    assert "Pydantic request • exactly one operation" in content
    assert "Required(..., calls=Exactly(1))" in content
    assert "≥1 FromRequest • immutable stable defaults only" in content
    assert "no ordering or unsupported sources" in content
    assert "operation output = endpoint output (exact identity)" in content
    assert "AGENTIC ENDPOINT" in content
    assert '@summon("/reports/agentic")' in content
    assert "AgentChoice()" in content
    assert "the agent owns only the declared semantic choice" in content
    assert "model-owned" not in content
    assert "Current runtime: eligible single-op slice runs directly" in content
    assert "every other declaration uses the agent runtime" in content


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
    assert "other operation shapes remain on the legacy agent-supplied path" in readme


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
