"""Tests for the canonical Summon application API."""

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_summon_is_the_public_application_type():
    from summonpot import Summon

    summon = Summon("svc")

    assert summon.name == "svc"
    assert type(summon).__name__ == "Summon"
    assert repr(summon).startswith("Summon('svc',")


def test_summon_instance_is_the_endpoint_decorator():
    from summonpot import Summon

    summon = Summon("svc")

    @summon("/research")
    def research(query: str) -> str:
        """Research this topic."""
        ...

    assert len(summon.endpoints) == 1
    assert summon.endpoints[0].path == "/research"
    assert summon.endpoints[0].name == "research"


def test_summon_method_remains_a_temporary_compatibility_alias():
    from summonpot import Summon

    summon = Summon("svc")

    @summon.summon("/legacy-spelling")
    def legacy_spelling(query: str) -> str:
        """Keep source compatibility while applications migrate."""
        ...

    assert summon.endpoints[0].path == "/legacy-spelling"


def test_pot_is_not_part_of_the_package_root_api():
    import summonpot

    assert not hasattr(summonpot, "Pot")
    assert "Pot" not in summonpot.__all__


def test_legacy_pot_module_is_not_part_of_the_package():
    with pytest.raises(ModuleNotFoundError, match=r"summonpot\.pot"):
        importlib.import_module("summonpot.pot")


def test_cli_loads_the_module_summon_variable(tmp_path: Path):
    from summonpot.cli import _load_summon

    source = tmp_path / "app.py"
    source.write_text(
        "from summonpot import Summon\nsummon = Summon('loaded')\n", encoding="utf-8"
    )

    loaded = _load_summon(str(source))

    assert loaded.name == "loaded"


def test_public_surfaces_use_the_summon_application_vocabulary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    canonical_readme = re.sub(
        r"^## Migrating from the 0\.5 API\n.*?(?=^## )",
        "",
        readme,
        flags=re.DOTALL | re.MULTILINE,
    )
    surfaces = [
        ROOT / "ROADMAP.md",
        ROOT / "src/summonpot/templates/skills/summonpot.md",
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("*.py")),
    ]
    contents = {
        ROOT / "README.md": canonical_readme,
        **{path: path.read_text(encoding="utf-8") for path in surfaces},
    }
    stale = {
        str(path.relative_to(ROOT)): sorted(
            set(
                re.findall(
                    r"\bPot\b|@pot\.summon|@summon\.summon|\bpot\s*=",
                    text,
                )
            )
        )
        for path, text in contents.items()
        if re.search(r"\bPot\b|@pot\.summon|@summon\.summon|\bpot\s*=", text)
    }

    assert stale == {}
