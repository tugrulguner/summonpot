"""Presentation guards for the repository's primary adoption surface."""

import re
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

    assert (
        '<img src="summonpot-lockup.png?v=wordmark-accent-1" alt="Summonpot" width="600">'
        in introduction
    )
    assert (
        "define the endpoint. summonpot owns the orchestration"
        in normalized_introduction
    )
    assert "exact application-owned operations" in normalized_introduction
    assert "summonpot orchestrates those operations" in normalized_introduction
    assert "bounded choice" in normalized_introduction
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


def test_minimal_lockup_preserves_the_canonical_compact_mark():
    image = ROOT / "summonpot-lockup.png"
    mark = (ROOT / "assets" / "summonpot-mark.svg").read_text(encoding="utf-8")
    lockup = (ROOT / "assets" / "summonpot-lockup.svg").read_text(encoding="utf-8")
    geometry = re.findall(r"<(?:path|circle|rect)\b[^>]*?/>", mark)

    data = image.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (1200, 900)
    assert geometry
    assert all(shape in lockup for shape in geometry)


def test_readme_states_the_current_runtime_boundary_before_positioning():
    readme = README.read_text(encoding="utf-8")
    introduction = _normalize(readme.split("## Why summonpot?", 1)[0])

    assert (
        "single-operation `exactly(1)` path executes without resolving or constructing"
        in introduction
    )
    assert "from version 0.12.0" in introduction
    assert "uniquely ordered required `exactly(1)` chains" in introduction
    assert "at least one `fromrequest` binding" in introduction
    assert "endpoint's exact full response annotation" in introduction
    assert (
        "remain agent-mediated except for the narrow result-dependent path included from version 0.14.0"
        in introduction
    )
    assert "bare legacy capabilities remain agent-mediated" in introduction
    assert "historical v0.13.0 behavior" in introduction
    assert "unsupported explicit contract shapes fail at registration" in introduction
    assert "broader graphs remain on the [roadmap](roadmap.md)" in introduction


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


def test_readme_adds_chain_diagram_after_preserved_overview_with_runnable_text_equivalent():
    readme = README.read_text(encoding="utf-8")
    introduction = readme.split("## Why summonpot?", 1)[0]
    overview = introduction.index("one-declaration-two-flows.png")
    chain = introduction.index("docs/assets/validated-producer-choice.png")
    source = ROOT / "docs/assets/validated-producer-choice.svg"
    raster = ROOT / "docs/assets/validated-producer-choice.png"

    assert overview < chain
    assert source.is_file() and raster.is_file()
    assert 'width="960" height="600"' in introduction
    assert "Open the full-size diagram" in introduction
    for claim in (
        "opaque tokens",
        "canonical objects",
        "token membership",
        "agent-mediated",
        "transactions and idempotency",
    ):
        assert claim in introduction


def test_homepage_and_execution_guide_keep_overview_before_new_chain():
    homepage = (ROOT / "website/src/content/docs/index.mdx").read_text(encoding="utf-8")
    execution = (ROOT / "website/src/content/docs/internals/execution.mdx").read_text(
        encoding="utf-8"
    )
    for text in (homepage, execution):
        overview = text.index("one-declaration-two-flows.png")
        chain = text.index("validated-producer-choice.png?v=0.11.0")
        assert overview < chain
        assert 'loading="lazy"' in text
        assert "Open full size" in text
        assert "opaque tokens" in text
        assert "agent-mediated" in text
        assert "idempotency" in text


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
    assert "unsupported explicit operation shapes are rejected before serving" in readme
    assert "`operation(fn)` is still an explicit contract" in readme


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
