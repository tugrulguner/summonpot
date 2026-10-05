"""Checks that the typed-package contract holds in the artifact, not just the tree.

`Typing :: Typed` in the metadata is a promise to type checkers, and PEP 561
says the marker file is how that promise is kept. A classifier without a
`py.typed` is a claim the installed distribution cannot back up, so both halves
are asserted together.
"""

from __future__ import annotations

import re
import tarfile
import textwrap
import tomllib
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest

import summonpot

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "summonpot"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PRODUCT_DESCRIPTION = (
    "A contract-first Python framework for modernizing APIs for AI through exact "
    "application behavior and explicitly bounded agent-owned decisions."
)


def test_py_typed_marker_sits_beside_the_package_init():
    """PEP 561 requires the marker inside the import package, not the sdist root."""
    marker = PACKAGE / "py.typed"

    assert marker.is_file(), (
        f"{marker} is missing; the Typing :: Typed classifier is unbacked"
    )
    assert (marker.parent / "__init__.py").is_file(), (
        "py.typed must live next to __init__.py, or type checkers will not find it"
    )


def test_py_typed_marker_is_empty():
    """PEP 561 defines the marker by presence; content would only invite drift."""
    assert (PACKAGE / "py.typed").read_bytes() == b""


def test_py_typed_ships_with_the_importable_package():
    """Resolve through the import system, so an install that dropped it fails here.

    `files()` points at whatever `import summonpot` actually resolved to -- the
    checkout under an editable install, site-packages under a real one -- which
    is the copy a consumer's type checker will look at.
    """
    assert files(summonpot).joinpath("py.typed").is_file()


def test_typed_classifier_is_declared():
    """The other half of the contract: drop one and this test names the other."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = metadata["project"]["classifiers"]

    assert "Typing :: Typed" in classifiers, (
        "py.typed ships but the classifier is gone; installers no longer advertise "
        "the package as typed"
    )


def test_package_metadata_and_module_lead_with_the_ai_api_positioning():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["description"] == PRODUCT_DESCRIPTION
    assert "Modernize APIs for AI" in (summonpot.__doc__ or "")


def _build_config() -> dict:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return metadata["tool"]["hatch"]["build"]["targets"]


@pytest.mark.parametrize("target", ["wheel", "sdist"])
def test_contributor_guidance_is_excluded_from_both_targets(target):
    """Hatchling configures the two targets separately.

    The wheel's `exclude` does not reach the sdist, so the sdist shipped both
    the root `AGENTS.md` and `src/summonpot/AGENTS.md` while the wheel shipped
    neither. The CI packaging job asserts this against the built artifacts;
    this test names the setting so dropping it fails here first.
    """
    assert "**/AGENTS.md" in _build_config()[target].get("exclude", [])
    assert "/CLAUDE.md" in _build_config()[target].get("exclude", [])
    assert "/.claude" in _build_config()[target].get("exclude", [])


@pytest.mark.parametrize("target", ["wheel", "sdist"])
def test_local_environments_and_build_output_are_explicitly_excluded(target):
    excluded = _build_config()[target].get("exclude", [])

    assert "/.venv*" in excluded
    assert "/dist" in excluded


def test_agents_guidance_is_what_is_being_excluded():
    """A guard on the guard: if the file is renamed, the pattern is now dead."""
    assert (ROOT / "AGENTS.md").is_file()
    assert (PACKAGE / "AGENTS.md").is_file()
    assert (ROOT / "CLAUDE.md").is_file()
    assert (ROOT / ".claude").is_dir()


@pytest.mark.parametrize("workflow", [CI_WORKFLOW, RELEASE_WORKFLOW])
@pytest.mark.parametrize("target", ["wheel", "sdist"])
@pytest.mark.parametrize(
    "member",
    [
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/skills/review.md",
        ".claude/",
        "project/AGENTS.md",
        "project/src/summonpot/CLAUDE.md",
        "project/.claude/skills/review.md",
        None,
    ],
)
def test_artifact_workflows_reject_all_contributor_guidance(
    workflow, target, member, tmp_path, monkeypatch
):
    """Execute each real workflow verifier against root and nested archive members."""
    text = workflow.read_text(encoding="utf-8")
    step = re.split(r"      - name: Verify (?:distribution|release) artifacts\n", text)[
        1
    ]
    script = textwrap.dedent(
        step.split("python3 - <<'PY'\n", 1)[1].split("          PY", 1)[0]
    )
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    # Similar names and the installed consumer skill must remain allowed.
    allowed = [
        "summonpot/__init__.py",
        "summonpot/py.typed",
        "summonpot/templates/skills/summonpot.md",
        "docs/NOT_AGENTS.md",
        "docs/CLAUDE.md.example",
        ".claude-backup/notes.md",
    ]
    with zipfile.ZipFile(dist / "summonpot.whl", "w") as archive:
        for name in allowed + ([member] if target == "wheel" and member else []):
            archive.writestr(name, b"")
    with tarfile.open(dist / "summonpot.tar.gz", "w:gz") as archive:
        names = [f"project/src/{name}" for name in allowed]
        names.extend(
            [
                "project/scripts/release_smoke.py",
                "project/examples/09_contract_boundaries/app.py",
            ]
        )
        if target == "sdist" and member:
            names.append(member)
        for name in names:
            archive.addfile(tarfile.TarInfo(name))

    if member is None:
        exec(compile(script, str(workflow), "exec"), {})
    else:
        with pytest.raises(AssertionError) as exc:
            exec(compile(script, str(workflow), "exec"), {})
        assert exc.value.args == ([member],)


def test_the_consumer_type_check_pins_its_pyright():
    """An unpinned `uvx pyright` moves the acceptance result with each release.

    It also resolves an unreviewed package on every run, so the version must
    match the one uv.lock resolves for development.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pinned = re.findall(r"uvx pyright@([0-9.]+)", workflow)

    assert pinned, "the consumer type-check must pin an exact Pyright version"
    assert "uvx pyright " not in workflow, (
        "an unpinned `uvx pyright` invocation remains"
    )

    lock = (ROOT / "uv.lock").read_text(encoding="utf-8").splitlines()
    marker = 'name = "pyright"'
    index = next((i for i, line in enumerate(lock) if line.strip() == marker), None)
    assert index is not None, "pyright is no longer a locked development dependency"
    locked = lock[index + 1].split("=")[1].strip().strip('"')
    assert set(pinned) == {locked}, (
        f"CI pins Pyright {pinned} but uv.lock resolves {locked}"
    )
