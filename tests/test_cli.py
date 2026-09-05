"""Tests for the summonpot command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from summonpot.cli import _load_summon, app
from summonpot.summon import Summon

runner = CliRunner()


def test_version_option_reads_installed_package_metadata():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.startswith("summonpot ")


def test_help_describes_the_endpoint_framework_not_an_agent_framework():
    result = runner.invoke(app, ["--help"])
    normalized_help = " ".join(result.stdout.split())

    assert result.exit_code == 0
    assert (
        "A contract-first Python framework for modernizing APIs for AI through exact "
        "application behavior and explicitly bounded agent-owned decisions."
    ) in normalized_help
    assert "signature-first" not in normalized_help.lower()
    assert "every endpoint is an agent" not in normalized_help.lower()


def test_load_summon_reports_missing_file(tmp_path: Path, capsys):
    missing = tmp_path / "missing.py"

    with pytest.raises(typer.Exit) as error:
        _load_summon(str(missing))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == f"Error: file not found: {missing.resolve()}\n"


def test_load_summon_reports_file_without_summon(tmp_path: Path, capsys):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(typer.Exit) as error:
        _load_summon(str(source))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == (
        f"Error: no 'summon' variable found in {source.resolve()}. "
        "Define a Summon instance named 'summon'.\n"
    )


def test_load_summon_rejects_a_variable_of_the_wrong_type(tmp_path: Path, capsys):
    source = tmp_path / "app.py"
    source.write_text("summon = 1\n", encoding="utf-8")

    with pytest.raises(typer.Exit) as error:
        _load_summon(str(source))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == (
        f"Error: 'summon' in {source.resolve()} is not a Summon instance. "
        "Define a Summon instance named 'summon'.\n"
    )


def test_load_summon_reports_import_error(tmp_path: Path, capsys):
    source = tmp_path / "broken.py"
    source.write_text("raise RuntimeError('broken app')\n", encoding="utf-8")

    with pytest.raises(typer.Exit) as error:
        _load_summon(str(source))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == f"Error loading {source.resolve()}: broken app\n"


def test_load_summon_returns_declared_instance(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text(
        "from summonpot import Summon\nsummon = Summon('loaded')\n", encoding="utf-8"
    )

    loaded = _load_summon(str(source))

    assert isinstance(loaded, Summon)
    assert loaded.name == "loaded"


def test_load_summon_does_not_shadow_the_stdlib(tmp_path: Path, monkeypatch):
    """The application's directory must not precede the stdlib on sys.path."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    (tmp_path / "types.py").write_text("SHADOWED = True\n", encoding="utf-8")
    source = tmp_path / "app.py"
    source.write_text(
        "from summonpot import Summon\nsummon = Summon('served')\n", encoding="utf-8"
    )

    _load_summon(str(source))

    entry = str(tmp_path.resolve())
    assert entry in sys.path, (
        "the application directory must stay importable while serving"
    )
    assert sys.path.index(entry) == len(sys.path) - 1
    assert sys.path[0] != entry


def test_load_summon_does_not_duplicate_sys_path_entries(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    source = tmp_path / "app.py"
    source.write_text(
        "from summonpot import Summon\nsummon = Summon('served')\n", encoding="utf-8"
    )

    _load_summon(str(source))
    _load_summon(str(source))

    assert sys.path.count(str(tmp_path.resolve())) == 1


def test_load_summon_reports_unloadable_file_once(tmp_path: Path, capsys):
    """typer.Exit subclasses RuntimeError and must not be caught as a load error."""
    source = tmp_path / "app.txt"
    source.write_text("summon = 1\n", encoding="utf-8")

    with pytest.raises(typer.Exit) as error:
        _load_summon(str(source))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == (
        f"Error: could not load module from {source.resolve()}\n"
    )


def test_load_summon_supports_dataclasses_in_the_application_file(tmp_path: Path):
    """dataclasses resolve annotations through sys.modules[cls.__module__]."""
    source = tmp_path / "app.py"
    source.write_text(
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "from summonpot import Summon\n"
        "\n"
        "@dataclass\n"
        "class Settings:\n"
        "    retries: int = 3\n"
        "\n"
        "summon = Summon('dataclass-app')\n",
        encoding="utf-8",
    )

    loaded = _load_summon(str(source))

    assert loaded.name == "dataclass-app"


def test_load_summon_does_not_leave_a_failed_module_in_sys_modules(tmp_path: Path):
    source = tmp_path / "broken.py"
    source.write_text("raise RuntimeError('broken app')\n", encoding="utf-8")
    before = set(sys.modules)

    with pytest.raises(typer.Exit):
        _load_summon(str(source))

    assert set(sys.modules) - before == set()


def test_serve_command_loads_and_serves_summon(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text(
        "from summonpot import Summon\nsummon = Summon('served')\n", encoding="utf-8"
    )

    with patch.object(Summon, "serve") as serve:
        result = runner.invoke(
            app,
            ["serve", str(source), "--host", "127.0.0.1", "--port", "9001"],
        )

    assert result.exit_code == 0
    assert "Summoning served on http://127.0.0.1:9001" in result.stdout
    serve.assert_called_once_with(host="127.0.0.1", port=9001)
