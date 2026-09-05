"""Install the summonpot skill into AI coding agent configuration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from pathlib import Path

import typer

from summonpot.skills.content import (
    SKILL_DESCRIPTION,
    SKILL_NAME,
    claude_skill,
    cline_rule,
    codex_instruction,
    copilot_instruction,
    cursor_rule,
    skill_body,
    windsurf_rule,
)

_MANAGED_START = "<!-- summonpot:managed:start -->"
_MANAGED_END = "<!-- summonpot:managed:end -->"


class MalformedManagedBlockError(Exception):
    """Raised when a shared file contains ambiguous managed-block markers.

    The fail-closed contract: the affected file is left byte-identical and the
    CLI exits non-zero with a message that names the affected relative path
    and explains how to repair the markers manually.
    """

    def __init__(
        self,
        path: Path,
        *,
        starts: int,
        ends: int,
        end_before_start: bool = False,
    ) -> None:
        self.path = path
        self.starts = starts
        self.ends = ends
        self.end_before_start = end_before_start

    def render(self, root: Path | None = None) -> str:
        target = self.path
        if root is not None:
            with suppress(ValueError):
                target = self.path.relative_to(root)
        lines = [
            f"Refusing to modify {target}: managed-block markers are malformed.",
            f"  Found {self.starts} start marker(s) and {self.ends} end marker(s).",
        ]
        if self.end_before_start:
            lines.append("  The end marker appears before the start marker.")
        if self.starts != 1 or self.ends != 1:
            lines.append("  Expected either 0 of each, or exactly one ordered pair.")
        lines.append(
            "  Repair the markers in this file manually, then re-run "
            "`summonpot add skills`."
        )
        return "\n".join(lines)


def _validate_managed_markers(text: str, path: Path) -> None:
    """Raise MalformedManagedBlockError if ``text`` has ambiguous managed markers.

    A file is well-formed when it contains either zero managed markers or
    exactly one start marker followed by exactly one end marker. Anything else
    (start-only, end-only, reversed, or duplicated markers) means the file's
    intent cannot be inferred safely and rewriting it would risk corrupting
    user-authored content.
    """
    starts = text.count(_MANAGED_START)
    ends = text.count(_MANAGED_END)

    if starts == 0 and ends == 0:
        return

    if (
        starts == 1
        and ends == 1
        and text.find(_MANAGED_START) < text.find(_MANAGED_END)
    ):
        return

    end_before_start = starts == 1 and ends == 1
    raise MalformedManagedBlockError(
        path,
        starts=starts,
        ends=ends,
        end_before_start=end_before_start,
    )


class Agent(StrEnum):
    """Coding agents summonpot can install its skill for."""

    claude = "claude"
    cursor = "cursor"
    windsurf = "windsurf"
    copilot = "copilot"
    cline = "cline"
    codex = "codex"


def _write_claude(root: Path) -> list[Path]:
    """Write a Claude Code skill to .claude/skills/<name>/SKILL.md."""
    skill_dir = root / ".claude" / "skills" / SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        claude_skill(skill_body(), name=SKILL_NAME, description=SKILL_DESCRIPTION),
        encoding="utf-8",
    )
    return [path]


def _write_cursor(root: Path) -> list[Path]:
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    path = rules / f"{SKILL_NAME}.mdc"
    path.write_text(
        cursor_rule(skill_body(), description=SKILL_DESCRIPTION), encoding="utf-8"
    )
    return [path]


def _write_windsurf(root: Path) -> list[Path]:
    rules = root / ".windsurf" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    path = rules / f"{SKILL_NAME}.md"
    path.write_text(
        windsurf_rule(skill_body(), description=SKILL_DESCRIPTION), encoding="utf-8"
    )
    return [path]


def _write_cline(root: Path) -> list[Path]:
    rules = root / ".clinerules"
    rules.mkdir(parents=True, exist_ok=True)
    path = rules / f"{SKILL_NAME}.md"
    path.write_text(cline_rule(skill_body()), encoding="utf-8")
    return [path]


def _write_copilot(root: Path) -> list[Path]:
    path = root / ".github" / "copilot-instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    _upsert_managed_block(path, copilot_instruction(skill_body()))
    return [path]


def _write_codex(root: Path) -> list[Path]:
    path = root / "AGENTS.md"
    _upsert_managed_block(path, codex_instruction(skill_body()))
    return [path]


def _dominant_newline(text: str) -> str:
    """The line ending the file already uses, so the block can match it.

    First occurrence rather than a count: a file is written by one editor with
    one convention, and a mixed file is already inconsistent, so following the
    majority there would still rewrite the minority. Matching the first ending
    keeps the block consistent with the top of the file, which is where the
    project's own instructions live.
    """
    index = text.find("\n")
    if index == -1:
        return "\n"
    return "\r\n" if index and text[index - 1] == "\r" else "\n"


def _upsert_managed_block(path: Path, content: str) -> None:
    """Write the skill into a shared file without disturbing the rest of it.

    Copilot and Codex read one file that the project also uses for its own
    instructions, so the skill is fenced in a managed block and replaced in place on
    re-run rather than appended again.

    Read and written with ``newline=""``, which turns off universal-newline
    translation in both directions. With it on, reading folded every ``\\r\\n``
    to ``\\n`` and writing expanded every ``\\n`` to ``os.linesep``, so updating
    the block rewrote the line endings of the *surrounding* content the command
    promises not to touch -- CRLF to LF on macOS and Linux, LF to CRLF on
    Windows. That is a whole-file diff for a change to one fenced region, and
    decoded-text assertions cannot see it because the translation is symmetric
    on the platform that performed it.
    """
    # `Path.read_text` only grew a `newline` argument in 3.13, and this package
    # supports 3.11, so the handle is opened directly on both sides.
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            existing = handle.read()
    else:
        existing = ""

    _validate_managed_markers(existing, path)

    # The block is authored with "\n" and re-expanded to whatever the file
    # already uses, so a managed block in a CRLF file stays CRLF.
    newline = _dominant_newline(existing)
    block = f"{_MANAGED_START}\n{content.rstrip()}\n{_MANAGED_END}\n"
    if newline != "\n":
        block = block.replace("\n", newline)

    start = existing.find(_MANAGED_START)
    end = existing.find(_MANAGED_END)
    if start != -1 and end != -1 and end > start:
        # Resume immediately after the marker, consuming a line ending only when one
        # is actually there. Assuming a trailing newline eats the first character of
        # whatever follows the block.
        after = end + len(_MANAGED_END)
        for ending in ("\r\n", "\n"):
            if existing.startswith(ending, after):
                after += len(ending)
                break
        updated = existing[:start] + block + existing[after:]
    elif existing.strip():
        updated = existing.rstrip() + newline * 2 + block
    else:
        updated = block

    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)


_WRITERS: dict[Agent, Callable[[Path], list[Path]]] = {
    Agent.claude: _write_claude,
    Agent.cursor: _write_cursor,
    Agent.windsurf: _write_windsurf,
    Agent.copilot: _write_copilot,
    Agent.cline: _write_cline,
    Agent.codex: _write_codex,
}

_MARKERS: dict[Agent, tuple[str, ...]] = {
    Agent.claude: (".claude",),
    Agent.cursor: (".cursor",),
    Agent.windsurf: (".windsurf",),
    # Not bare .github/: that exists for workflows and Dependabot in almost every
    # repository, and is no evidence that Copilot instructions are in use.
    Agent.copilot: (".github/copilot-instructions.md",),
    Agent.cline: (".clinerules",),
    Agent.codex: ("AGENTS.md",),
}


def detect_agents(root: Path) -> list[Agent]:
    """Return the agents this project already has configuration for."""
    return [
        agent
        for agent, markers in _MARKERS.items()
        if any((root / marker).exists() for marker in markers)
    ]


def add_skills(
    agent: Agent | None = typer.Option(
        None,
        "--agent",
        help="Install for one agent. Defaults to every agent already configured here.",
    ),
    path: Path = typer.Option(
        Path("."),
        "--path",
        help="Project directory to install into.",
    ),
) -> None:
    """Install the summonpot skill so a coding agent knows the endpoint contract."""
    root = path.resolve()
    if not root.is_dir():
        typer.echo(f"Error: not a directory: {root}", err=True)
        raise typer.Exit(1)

    if agent is not None:
        targets = [agent]
    else:
        targets = detect_agents(root)
        if not targets:
            typer.echo(
                "No agent configuration found here. Pass --agent to choose one of: "
                + ", ".join(a.value for a in Agent),
                err=True,
            )
            raise typer.Exit(1)

    for target in targets:
        try:
            written_paths = _WRITERS[target](root)
        except MalformedManagedBlockError as exc:
            typer.echo(exc.render(root), err=True)
            raise typer.Exit(1) from exc
        for written in written_paths:
            typer.echo(f"{target.value}: {written.relative_to(root)}")
