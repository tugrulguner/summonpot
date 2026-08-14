"""summonpot CLI — serve your Pot from the command line."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import typer

from summonpot.pot import Pot


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        typer.echo(f"summonpot {version('summonpot')}")
        raise typer.Exit()


app = typer.Typer(
    name="summonpot",
    help="An AI-native API framework. Every endpoint is an agent that runs automatically.",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """An API framework where every endpoint is an agent."""


@app.command("serve")
def serve_command(
    source: str = typer.Argument(
        ...,
        help="Path to a Python file containing a Pot instance named 'pot'.",
    ),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to."),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to."),
) -> None:
    """Serve a Pot file as an HTTP API."""
    pot = _load_pot(source)
    typer.echo(f"Summoning {pot.name} on http://{host}:{port}")
    pot.serve(host=host, port=port)


def _load_pot(source: str) -> Pot:
    """Load a Pot instance from a Python file."""
    filepath = Path(source).resolve()
    if not filepath.exists():
        typer.echo(f"Error: file not found: {filepath}", err=True)
        raise typer.Exit(1)

    sys.path.insert(0, str(filepath.parent))
    # Raised outside the try below: typer.Exit subclasses RuntimeError, so an
    # `except Exception` around this would catch it and report the exit code
    # as though it were a load error.
    spec = importlib.util.spec_from_file_location("_summonpot_user", filepath)
    if spec is None or spec.loader is None:
        typer.echo(f"Error: could not load module from {filepath}", err=True)
        raise typer.Exit(1)

    mod = importlib.util.module_from_spec(spec)
    # Register before execution: dataclasses, typing.get_type_hints, enum
    # resolution, and pickling all look the defining module up in sys.modules.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        sys.modules.pop(spec.name, None)
        typer.echo(f"Error loading {filepath}: {e}", err=True)
        raise typer.Exit(1) from None
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise

    pot = getattr(mod, "pot", None)
    if pot is None:
        typer.echo(
            f"Error: no 'pot' variable found in {filepath}. "
            "Define a Pot instance named 'pot'.",
            err=True,
        )
        raise typer.Exit(1)
    return pot
