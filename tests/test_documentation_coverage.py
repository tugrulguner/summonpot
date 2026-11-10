"""Catalog/link regressions use discovered entrypoints, not frozen application counts."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _entrypoints():
    return {
        path.relative_to(EXAMPLES).as_posix()
        for path in EXAMPLES.rglob("*.py")
        if path.parent == EXAMPLES or path.name == "app.py"
    }


def _catalog_target(target):
    if target.rstrip("/") == "examples":
        return None
    path = ROOT / target
    if path.name == "README.md":
        path = path.parent / "app.py"
    elif path.is_dir():
        path = path / "app.py"
    if not path.is_relative_to(EXAMPLES):
        return None
    return path.relative_to(EXAMPLES).as_posix()


def test_readme_catalog_covers_every_discovered_application():
    text = (ROOT / "README.md").read_text()
    section = text.split("## Examples\n", 1)[1].split("\n## ", 1)[0]
    targets = re.findall(r"\]\((examples/[^)]+)\)", section)
    actual = {_catalog_target(target) for target in targets} - {None}
    assert _entrypoints() <= actual


def test_example_progression_headings_match_their_actual_application():
    text = (EXAMPLES / "README.md").read_text()
    progression = text.split("## Progression\n", 1)[1].split("\n## ", 1)[0]
    matches = list(re.finditer(r"^### ([0-9]+[ab]?)\. .+$", progression, re.M))
    sections = {
        match.group(1): progression[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else None
        ]
        for i, match in enumerate(matches)
    }
    for entry in sorted(_entrypoints()):
        if entry == "basic_app.py":
            level, identity = "1", entry
        else:
            identity = entry.split("/")[0]
            level = str(int(identity.split("_", 1)[0]))
            if identity == "13_authenticated_context":
                level = "13a"
            elif identity == "13_multiple_producer_choices":
                level = "13b"
        assert level in sections, f"Missing distinct progression heading for {entry}"
        assert identity in sections[level], (
            f"Heading {level} describes another app, not {entry}"
        )


def test_local_documentation_path_targets_exist():
    files = [ROOT / "README.md", ROOT / "ROADMAP.md", ROOT / "CONTRIBUTING.md"]
    files += sorted((ROOT / "docs").glob("*.md"))
    files += sorted(EXAMPLES.rglob("README.md"))
    missing = []
    for path in files:
        text = path.read_text()
        for match in re.finditer(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
            target = urlsplit(match.group(1))
            if (
                target.scheme
                or target.netloc
                or not target.path
                or target.path.startswith("/")
            ):
                continue
            destination = path.parent / unquote(target.path)
            if not destination.exists():
                missing.append((str(path.relative_to(ROOT)), match.group(1)))
    assert not missing


def test_old_reviewing_guidance_no_longer_defers_implemented_ordering():
    text = " ".join((ROOT / "docs/reviewing.md").read_text().split())
    assert "runtime ordering enforcement remains planned" not in text
    assert "authenticated context" in text
    assert "runtime ordering is enforced in supported chains" in text


def test_focused_lessons_are_discoverable_from_site_and_packaged_skill():
    required = {
        "website/src/content/docs/index.mdx": (
            "21_path_methods",
            "22_contract_defaults",
        ),
        "website/src/content/docs/guides/operations.mdx": (
            "21_path_methods",
            "22_contract_defaults",
        ),
        "website/src/content/docs/tasks/direct-execution.mdx": (
            "22_contract_defaults",
        ),
        "src/summonpot/templates/skills/summonpot.md": (
            "21_path_methods",
            "22_contract_defaults",
        ),
    }
    for filename, lessons in required.items():
        text = (ROOT / filename).read_text()
        for lesson in lessons:
            assert lesson in text, (filename, lesson)


def test_skill_activation_includes_existing_path_parameter_capability():
    from summonpot.skills.content import SKILL_DESCRIPTION

    assert "HTTP methods" in SKILL_DESCRIPTION
    assert "path parameters" in SKILL_DESCRIPTION
