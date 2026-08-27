"""Contract tests for contributor entry points and templates."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AGENT_GUIDE = ROOT / "AGENTS.md"
PR_REVIEW_SKILL = ROOT / ".claude" / "skills" / "pr-review" / "SKILL.md"
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
    for heading in (
        "## Summary",
        "## Related issue",
        "## Scope and non-goals",
        "## User-visible behavior",
        "## Verification",
        "## Documentation and contracts",
        "## Changelog",
        "## Safety",
    ):
        assert heading in pull_request_template
    assert "Closes #" in pull_request_template
    assert "make check" in pull_request_template
    assert "make build" in pull_request_template


def test_issue_forms_define_the_shared_contribution_contract() -> None:
    bug = _text(ISSUE_FORMS / "bug.yml")
    feature = _text(ISSUE_FORMS / "feature.yml")
    chooser = _text(ISSUE_FORMS / "config.yml")

    assert 'name: "Bug report"' in bug
    assert "Summonpot version or source revision" in bug
    assert "Model and provider" in bug
    assert "Minimal runnable application" in bug
    assert "Contribution intent" in bug
    assert "removed API keys" in bug

    assert 'name: "Feature request"' in feature
    for field in (
        "Problem",
        "What happens now",
        "Why I want it",
        "Concrete use case",
        "Proposed solution",
        "Acceptance criteria",
        "Open question",
        "Implementation notes",
        "Alternatives considered",
        "Scope and non-goals",
        "Contribution intent",
    ):
        assert field in feature
    assert "wait for contract alignment" in feature

    assert "blank_issues_enabled: false" in chooser
    assert "/discussions/categories/q-a" in chooser
    assert "/discussions/categories/ideas-roadmap" in chooser


def test_issue_forms_parse_and_have_unique_field_ids() -> None:
    for name in ("bug.yml", "feature.yml"):
        form = yaml.safe_load(_text(ISSUE_FORMS / name))
        ids = [item["id"] for item in form["body"] if "id" in item]

        assert ids
        assert len(ids) == len(set(ids))


def test_contributing_states_the_supported_binding_slice_precisely() -> None:
    contributing = re.sub(r"\s+", " ", _text(CONTRIBUTING))

    assert "single-required-operation `Exactly(1)` slice" in contributing
    assert (
        "supported `FromRequest`, direct `AgentChoice`, and callable-default bindings"
        in contributing
    )
    assert (
        "Unsupported binding shapes, including `FromContext`, remain model-supplied"
        in contributing
    )


def test_reviewing_separates_shipped_ordering_validation_from_runtime_enforcement() -> (
    None
):
    reviewing = _text(REVIEWING)

    assert (
        "Ordering declarations and their registration-time validation have shipped"
        in reviewing
    )
    assert "runtime ordering enforcement remains planned" in reviewing


def test_templates_preserve_summonpot_contract_boundaries() -> None:
    feature = _text(ISSUE_FORMS / "feature.yml")
    pull_request_template = _text(PULL_REQUEST_TEMPLATE)
    reviewing = _text(REVIEWING)

    assert "model-backed" in feature
    assert "public graph" in feature
    assert "model-controlled" in pull_request_template
    assert "redacted public errors" in pull_request_template
    assert "remain planned" in reviewing


def test_contribution_docs_use_issue_or_orphan_changelog_fragments() -> None:
    agent_guide = _text(AGENT_GUIDE)
    contributing = _text(CONTRIBUTING)
    pull_request_template = _text(PULL_REQUEST_TEMPLATE)
    guide = _text(CHANGELOG_GUIDE)
    workflow = _text(CHANGELOG_WORKFLOW)
    config = tomllib.loads(_text(ROOT / "pyproject.toml"))["tool"]["towncrier"]

    pr_review_skill = _text(PR_REVIEW_SKILL)
    for document in (agent_guide, pr_review_skill, contributing, guide):
        assert "<issue-number>.<type>.md" in document
        assert "towncrier create +.changed.md" in document
    assert "<issue-number>.<type>.md" in pull_request_template
    assert "+<identifier>.<type>.md" in pull_request_template

    assert "\\+[A-Za-z0-9]" in workflow
    assert 'select(.status != "removed") | .filename' in workflow
    assert "issues: read" in workflow
    assert "issues/${issue_number}" in workflow
    assert "must use an issue number" in workflow
    assert "pull/{issue}" not in config["issue_format"]
    assert config["issue_format"].endswith("/issues/{issue})")


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
