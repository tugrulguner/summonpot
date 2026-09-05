"""Tests for `summonpot add skills`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from summonpot.cli import app
from summonpot.commands.add_skills import Agent, detect_agents

runner = CliRunner()

EXPECTED: dict[str, str] = {
    "claude": ".claude/skills/summonpot/SKILL.md",
    "cursor": ".cursor/rules/summonpot.mdc",
    "windsurf": ".windsurf/rules/summonpot.md",
    "copilot": ".github/copilot-instructions.md",
    "cline": ".clinerules/summonpot.md",
    "codex": "AGENTS.md",
}


@pytest.mark.parametrize(("agent", "relative"), sorted(EXPECTED.items()))
def test_skill_is_written_where_the_agent_reads_it(agent, relative, tmp_path: Path):
    result = runner.invoke(
        app, ["add", "skills", "--agent", agent, "--path", str(tmp_path)]
    )

    assert result.exit_code == 0
    written = tmp_path / relative
    assert written.is_file()
    assert "@summon" in written.read_text(encoding="utf-8")


def test_claude_skill_has_the_frontmatter_that_makes_it_discoverable(tmp_path: Path):
    """Claude Code never loads a skill file without name and description."""
    runner.invoke(app, ["add", "skills", "--agent", "claude", "--path", str(tmp_path)])

    text = (tmp_path / ".claude/skills/summonpot/SKILL.md").read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert '"summonpot"' in text.split("---")[1]
    assert "description:" in text.split("---")[1]


def test_shared_files_keep_their_own_content(tmp_path: Path):
    """AGENTS.md belongs to the project; the skill is a fenced guest."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# My project\n\nExisting notes.\n", encoding="utf-8")

    runner.invoke(app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)])
    text = agents.read_text(encoding="utf-8")

    assert "# My project" in text
    assert "Existing notes." in text
    assert "summonpot:managed:start" in text


def test_reinstalling_replaces_the_block_rather_than_appending(tmp_path: Path):
    for _ in range(3):
        runner.invoke(
            app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)]
        )

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").count(
        "summonpot:managed:start"
    ) == 1


def test_agents_are_detected_from_existing_configuration(tmp_path: Path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".clinerules").mkdir()

    assert set(detect_agents(tmp_path)) == {Agent.claude, Agent.cline}


def test_install_without_an_agent_uses_what_the_project_already_has(tmp_path: Path):
    (tmp_path / ".cursor").mkdir()

    result = runner.invoke(app, ["add", "skills", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / ".cursor/rules/summonpot.mdc").is_file()
    assert not (tmp_path / ".claude").exists()


def test_install_with_nothing_to_detect_explains_the_choices(tmp_path: Path):
    result = runner.invoke(app, ["add", "skills", "--path", str(tmp_path)])

    assert result.exit_code == 1
    assert "--agent" in result.output
    assert "claude" in result.output


@pytest.mark.parametrize("eol", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_updating_the_block_leaves_surrounding_line_endings_untouched(
    eol: bytes, tmp_path: Path
):
    """Byte-level, because decoded text cannot see this.

    Universal-newline translation is symmetric on the platform that performs
    it, so reading back with ``read_text`` returns what you wrote regardless.
    Only the bytes on disk show that a command scoped to one fenced region
    rewrote the user's own lines around it.
    """
    agents = tmp_path / "AGENTS.md"
    before = eol.join([b"# Project rules", b"", b"Keep these.", b""])
    after = eol.join([b"", b"## Notes", b"Keep these too.", b""])
    agents.write_bytes(
        before
        + b"<!-- summonpot:managed:start -->"
        + eol
        + b"old"
        + eol
        + b"<!-- summonpot:managed:end -->"
        + after
    )

    result = runner.invoke(
        app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)]
    )
    assert result.exit_code == 0

    written = agents.read_bytes()
    assert written.startswith(before)
    assert written.endswith(after)

    # And the block the command owns matches the file it was written into,
    # rather than leaving one region on a different convention.
    other = b"\n" if eol == b"\r\n" else b"\r\n"
    if eol == b"\r\n":
        assert written.count(b"\r\n") == written.count(b"\n")
    else:
        assert other not in written


def test_a_new_shared_file_is_written_with_line_feeds(tmp_path: Path):
    """With no existing convention to follow, the block picks the portable one."""
    runner.invoke(app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)])

    assert b"\r\n" not in (tmp_path / "AGENTS.md").read_bytes()


@pytest.mark.parametrize(
    ("trailing", "expected_tail"),
    [
        ("AFTER", "AFTER"),  # marker followed directly by content
        ("\nAFTER", "AFTER"),  # marker followed by LF
        ("\r\nAFTER", "AFTER"),  # marker followed by CRLF
        ("", ""),  # marker at end of file
    ],
)
def test_reinstall_keeps_content_that_follows_the_block(
    trailing, expected_tail, tmp_path: Path
):
    """Assuming a trailing newline eats the first character after the block."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "<!-- summonpot:managed:start -->\nold\n<!-- summonpot:managed:end -->"
        + trailing,
        encoding="utf-8",
    )

    runner.invoke(app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)])
    text = agents.read_text(encoding="utf-8")

    # Ending with the exact trailing text is what proves no character was eaten:
    # the old code turned "AFTER" into "FTER".
    assert text.count("summonpot:managed:start") == 1
    assert text.endswith(expected_tail)


def test_a_bare_github_directory_is_not_copilot_configuration(tmp_path: Path):
    """.github exists for workflows and Dependabot in almost every repository."""
    (tmp_path / ".github").mkdir()

    assert detect_agents(tmp_path) == []

    result = runner.invoke(app, ["add", "skills", "--path", str(tmp_path)])

    assert result.exit_code == 1
    assert not (tmp_path / ".github/copilot-instructions.md").exists()


def test_an_existing_copilot_instructions_file_is_detected(tmp_path: Path):
    instructions = tmp_path / ".github" / "copilot-instructions.md"
    instructions.parent.mkdir(parents=True)
    instructions.write_text("# House rules\n", encoding="utf-8")

    assert detect_agents(tmp_path) == [Agent.copilot]


@pytest.mark.parametrize(
    ("label", "pre_existing"),
    [
        (
            "start-only",
            "<!-- summonpot:managed:start -->\npartial block\n",
        ),
        (
            "end-only",
            "<!-- summonpot:managed:end -->\n",
        ),
        (
            "reversed",
            "<!-- summonpot:managed:end -->stuff<!-- summonpot:managed:start -->\n",
        ),
        (
            "duplicate-start",
            "<!-- summonpot:managed:start -->\nA\n<!-- summonpot:managed:end -->"
            "<!-- summonpot:managed:start -->\nB\n",
        ),
        (
            "duplicate-end",
            "<!-- summonpot:managed:start -->\nA\n<!-- summonpot:managed:end -->"
            "<!-- summonpot:managed:end -->\n",
        ),
    ],
)
def test_malformed_managed_markers_fail_closed(label, pre_existing, tmp_path: Path):
    """Ambiguous managed markers must be left byte-identical."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text(pre_existing)
    snapshot = agents.read_bytes()

    result = runner.invoke(
        app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)]
    )

    assert result.exit_code == 1, result.output
    assert agents.read_bytes() == snapshot, f"file was modified for {label}"
    assert "Refusing to modify" in result.output
    assert "AGENTS.md" in result.output


def test_malformed_marker_error_explains_manual_repair(tmp_path: Path):
    """The CLI error names the path and tells the user how to repair manually."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text("<!-- summonpot:managed:start -->\npartial block\n")

    result = runner.invoke(
        app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "Repair the markers" in result.output
    assert "summonpot add skills" in result.output


def test_malformed_markers_fail_closed_for_copilot_instructions(tmp_path: Path):
    """The fail-closed contract also applies to .github/copilot-instructions.md."""
    instructions = tmp_path / ".github" / "copilot-instructions.md"
    instructions.parent.mkdir(parents=True)
    instructions.write_text("<!-- summonpot:managed:start -->\npartial\n")
    snapshot = instructions.read_bytes()

    result = runner.invoke(
        app, ["add", "skills", "--agent", "copilot", "--path", str(tmp_path)]
    )

    assert result.exit_code == 1, result.output
    assert instructions.read_bytes() == snapshot
    assert ".github/copilot-instructions.md" in result.output
