from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "mcr.microsoft.com/playwright:v1.63.0-noble@sha256:"
    "eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27"
)
TRUST_STEP = {
    "name": "Trust checkout for container-owned Git",
    "working-directory": ".",
    "run": 'git config --global --add safe.directory "$GITHUB_WORKSPACE"',
}


def _workflow(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text())


def test_playwright_website_jobs_use_pinned_container_and_preserve_gates() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    ci_jobs = ci["jobs"]
    website = ci_jobs["website"]
    assert website["container"] == {
        "image": IMAGE,
        "options": "--init --shm-size=1g",
    }
    ci_steps = website["steps"]
    assert TRUST_STEP in ci_steps
    commands = [step.get("run", "") for step in ci_steps]
    assert "npm ci" in commands
    assert "npm run check" in commands
    assert "npm run build" in commands
    assert any("1.63.0" in command for command in commands)
    assert not any(
        "playwright install" in command or "--with-deps" in command
        for command in commands
    )
    assert {"lint", "typecheck", "test", "build"}.issubset(ci_jobs)


def test_deploy_workflow_is_pinned_trusted_and_manual_dispatch_is_main_only() -> None:
    deploy = _workflow(".github/workflows/deploy-website.yml")
    job = deploy["jobs"]["deploy"]
    assert job["container"] == {
        "image": IMAGE,
        "options": "--init --shm-size=1g",
    }
    assert (
        job["if"]
        == "github.event_name != 'workflow_dispatch' || github.ref == 'refs/heads/main'"
    )
    steps = job["steps"]
    assert TRUST_STEP in steps
    commands = [step.get("run", "") for step in steps]
    assert "npm ci" in commands
    assert "npm run check" in commands
    assert "npm run build" in commands
    assert "npx wrangler deploy" in commands
    assert not any(
        "playwright install" in command or "--with-deps" in command
        for command in commands
    )
    assert deploy[True]["workflow_dispatch"] is None
