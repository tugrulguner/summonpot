"""Skill content and per-agent formatting.

summonpot ships one skill describing the endpoint contract. Each supported agent
reads a different file in a different place, so the body is written once here and
wrapped per agent.
"""

from __future__ import annotations

import json
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "templates" / "skills"

SKILL_NAME = "summonpot"
SKILL_TITLE = "summonpot endpoints"
SKILL_DESCRIPTION = (
    "Write and review summonpot @summon endpoint contracts. Use when declaring "
    "request and response models, Depends, Required, Operation bindings, model and "
    "runtime limits, HTTP methods, or serving an application. The declaration body is "
    "`...`."
)


def skill_body() -> str:
    """Return the endpoint-contract skill content."""
    return (_SKILLS_DIR / "summonpot.md").read_text(encoding="utf-8")


def claude_skill(body: str, *, name: str, description: str) -> str:
    """Format as a Claude Code skill (.claude/skills/<name>/SKILL.md).

    Claude Code discovers a skill through its YAML frontmatter: `name` identifies it
    and `description` decides whether it is loaded. A file without frontmatter is
    never read, so the body alone would be inert.
    """
    return (
        f"---\n"
        f"name: {json.dumps(name)}\n"
        f"description: {json.dumps(description)}\n"
        f"---\n\n"
        f"{body}"
    )


def cursor_rule(body: str, *, description: str) -> str:
    """Format as an intelligently activated Cursor rule."""
    return (
        f"---\n"
        f"description: {json.dumps(description)}\n"
        f"alwaysApply: false\n"
        f"---\n\n"
        f"{body}"
    )


def windsurf_rule(body: str, *, description: str) -> str:
    """Format as a model-decision Windsurf rule."""
    return (
        f"---\n"
        f"trigger: model_decision\n"
        f"description: {json.dumps(description)}\n"
        f"---\n\n"
        f"{body}"
    )


def copilot_instruction(body: str) -> str:
    """Format for GitHub Copilot (.github/copilot-instructions.md)."""
    return body


def cline_rule(body: str) -> str:
    """Format as a Cline rule (a .md file under .clinerules/)."""
    return body


def codex_instruction(body: str) -> str:
    """Format for OpenAI Codex CLI (AGENTS.md)."""
    return body
