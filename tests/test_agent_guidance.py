"""Regression tests for contributor-facing agent guidance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
REVIEW_SKILL = ROOT / ".claude/skills/review-code/SKILL.md"


def review_skill() -> str:
    return REVIEW_SKILL.read_text()


def test_review_verification_never_manipulates_the_users_stash():
    guidance = review_skill()

    assert "git stash" not in guidance
    assert "git worktree" in guidance
    assert "isolated" in guidance


def test_review_guidance_points_to_the_current_registration_entrypoint():
    guidance = review_skill()
    normalized = " ".join(guidance.split())

    assert "`Summon.__call__()`" in guidance
    assert "`src/summonpot/summon.py`" in guidance
    assert "registration entry point" in normalized
    assert "`src/summonpot/tools.py`" in guidance
    assert "`src/summonpot/_validation.py`" in guidance
    assert "`pot.py`" not in guidance


def test_root_guidance_documents_the_shipped_direct_path():
    guidance = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())

    assert "Today every request runs through" not in guidance
    assert "Pydantic request endpoint executes directly" in guidance
    assert "Required(..., calls=Exactly(1))" in guidance
    assert "at least one `FromRequest`" in guidance
    assert "supported immutable callable defaults" in guidance
    assert "never falls back to a model" in guidance
    assert (
        "All other declarations retain the provider-neutral agent runtime" in guidance
    )
