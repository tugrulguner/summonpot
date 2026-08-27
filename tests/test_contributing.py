"""Contract tests for contributor entry points and templates."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
REVIEWING = ROOT / "docs" / "reviewing.md"
ISSUE_FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
PULL_REQUEST_TEMPLATE = ROOT / ".github" / "pull_request_template.md"
CHANGELOG_GUIDE = ROOT / "changelog.d" / "README.md"
CHANGELOG_WORKFLOW = ROOT / ".github" / "workflows" / "changelog.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_contributor_entry_points_are_actionable() -> None:
    contributing = _text(CONTRIBUTING)
    pull_request_template = _text(PULL_REQUEST_TEMPLATE)

    assert "issues/new?template=bug.yml" in contributing
    assert "issues/new?template=feature.yml" in contributing
    assert "github.com/tugrulguner/summonpot/discussions" in contributing
    assert "comment and wait for confirmation" in contributing
    assert "Closes #<issue-number>" in contributing
    assert "docs/reviewing.md" in contributing
    assert "Closes #" in pull_request_template
    assert "make check" in pull_request_template
    assert "make build" in pull_request_template
    assert "Scope and non-goals" in pull_request_template


def test_issue_forms_and_discussion_chooser_are_present() -> None:
    bug = _text(ISSUE_FORMS / "bug.yml")
    feature = _text(ISSUE_FORMS / "feature.yml")
    chooser = _text(ISSUE_FORMS / "config.yml")

    assert 'name: "Bug report"' in bug
    assert "Summonpot version or source revision" in bug
    assert "Model and provider" in bug
    assert "Minimal runnable application" in bug
    assert "removed API keys" in bug
    assert 'name: "Feature request"' in feature
    assert "What happens now" in feature
    assert "Why I want it" in feature
    assert "Acceptance criteria" in feature
    assert "Scope and non-goals" in feature
    assert "wait for contract alignment" in feature
    assert "blank_issues_enabled: false" in chooser
    assert "/discussions/categories/q-a" in chooser
    assert "/discussions/categories/ideas-roadmap" in chooser


def test_templates_preserve_summonpot_contract_boundaries() -> None:
    contributing = _text(CONTRIBUTING)
    feature = _text(ISSUE_FORMS / "feature.yml")
    pull_request_template = _text(PULL_REQUEST_TEMPLATE)
    reviewing = _text(REVIEWING)
    combined = "\n".join(
        [contributing, feature, pull_request_template, reviewing]
    ).lower()

    assert "model-backed" in combined
    assert "planned architecture" in combined
    assert "public graph" in combined
    assert "model-controlled" in combined
    assert "redacted public errors" in combined


def test_contribution_docs_use_exact_pull_request_numbered_fragments() -> None:
    contributing = _text(CONTRIBUTING)
    pull_request_template = _text(PULL_REQUEST_TEMPLATE)
    guide = _text(CHANGELOG_GUIDE)
    workflow = _text(CHANGELOG_WORKFLOW)

    assert "<pull-request-number>.<type>.md" in contributing
    assert "<pull-request-number>.<type>.md" in pull_request_template
    assert "<pr-number>.<type>.md" in guide
    assert "${PR_NUMBER}" in workflow
    assert "towncrier create +" not in contributing
    assert "<issue-number>.<type>.md" not in contributing


def test_contribution_document_links_resolve() -> None:
    missing: list[str] = []
    for source in (CONTRIBUTING, REVIEWING):
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", _text(source)):
            if "://" in target or target.startswith("#"):
                continue
            path = source.parent / target.split("#", 1)[0]
            if not path.exists():
                missing.append(f"{source.relative_to(ROOT)} -> {target}")

    assert missing == []
