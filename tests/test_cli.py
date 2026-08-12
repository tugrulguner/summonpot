"""Tests for the summonpot command-line interface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from summonpot.cli import _load_pot, app
from summonpot.pot import Pot

runner = CliRunner()


def test_version_option_reads_installed_package_metadata():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.startswith("summonpot ")


def test_load_pot_reports_missing_file(tmp_path: Path, capsys):
    missing = tmp_path / "missing.py"

    with pytest.raises(typer.Exit) as error:
        _load_pot(str(missing))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == f"Error: file not found: {missing.resolve()}\n"


def test_load_pot_reports_file_without_pot(tmp_path: Path, capsys):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n")

    with pytest.raises(typer.Exit) as error:
        _load_pot(str(source))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == (
        f"Error: no 'pot' variable found in {source.resolve()}. "
        "Define a Pot instance named 'pot'.\n"
    )


def test_load_pot_reports_import_error(tmp_path: Path, capsys):
    source = tmp_path / "broken.py"
    source.write_text("raise RuntimeError('broken app')\n")

    with pytest.raises(typer.Exit) as error:
        _load_pot(str(source))

    assert error.value.exit_code == 1
    assert capsys.readouterr().err == f"Error loading {source.resolve()}: broken app\n"


def test_load_pot_returns_declared_instance(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text("from summonpot import Pot\npot = Pot('loaded')\n")

    loaded = _load_pot(str(source))

    assert isinstance(loaded, Pot)
    assert loaded.name == "loaded"


def test_serve_command_loads_and_serves_pot(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text("from summonpot import Pot\npot = Pot('served')\n")

    with patch.object(Pot, "serve") as serve:
        result = runner.invoke(
            app,
            ["serve", str(source), "--host", "127.0.0.1", "--port", "9001"],
        )

    assert result.exit_code == 0
    assert "Summoning served on http://127.0.0.1:9001" in result.stdout
    serve.assert_called_once_with(host="127.0.0.1", port=9001)
