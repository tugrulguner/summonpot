"""Launch every documented example through the installed Summonpot CLI."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExampleCase:
    source: str
    method: str
    path: str
    payload: dict[str, Any] | None = None


CASES = (
    ExampleCase("basic_app.py", "POST", "/review", {"text": "Clear contract."}),
    ExampleCase(
        "02_required_capability.py",
        "POST",
        "/quotes",
        {"unit_price_cents": 1299, "quantity": 3, "tax_rate_percent": "8.25"},
    ),
    ExampleCase(
        "03_agentic_order.py",
        "POST",
        "/orders",
        {
            "customer_id": "customer-7",
            "sku": "red-mug",
            "quantity": 2,
            "allow_substitute": True,
        },
    ),
    ExampleCase(
        "04_http_methods.py",
        "GET",
        "/products?category=stationery&max_price_cents=1500",
    ),
    ExampleCase(
        "05_bounded_runtime.py",
        "POST",
        "/summaries",
        {"text": "Summonpot keeps endpoint authority bounded.", "max_sentences": 2},
    ),
    ExampleCase(
        "06_support_service/app.py",
        "POST",
        "/support",
        {"customer_id": "customer-1", "message": "The API is unavailable."},
    ),
    ExampleCase(
        "07_bound_operation.py",
        "POST",
        "/customers/view",
        {"customer_id": "customer-7"},
    ),
    ExampleCase(
        "08_direct_execution.py",
        "POST",
        "/quotes/direct",
        {"unit_price_cents": 1299, "quantity": 3, "tax_rate_percent": "8.25"},
    ),
    ExampleCase(
        "09_contract_boundaries/app.py",
        "POST",
        "/customers/view",
        {"customerId": "customer-7"},
    ),
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, bytes]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _wait_until_ready(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"server exited with {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            status, _ = _request(base_url, "GET", "/openapi.json")
        except (OSError, TimeoutError):
            time.sleep(0.05)
            continue
        if status == 200:
            return
        time.sleep(0.05)
    raise TimeoutError(f"server did not become ready at {base_url}")


def _cli_path() -> str:
    beside_python = Path(sys.executable).with_name("summonpot")
    if beside_python.is_file():
        return str(beside_python)
    discovered = shutil.which("summonpot")
    if discovered is None:
        raise RuntimeError("summonpot console script is not installed")
    return discovered


def _smoke_environment(**updates: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(updates)
    return environment


def _verify_installed_version() -> str:
    expected = importlib.metadata.version("summonpot")
    result = subprocess.run(
        [_cli_path(), "--version"],
        check=False,
        capture_output=True,
        env=_smoke_environment(),
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"summonpot --version exited with {result.returncode}: {result.stderr}"
        )
    reported = result.stdout.strip()
    if reported != f"summonpot {expected}":
        raise AssertionError(
            f"summonpot --version reported {reported!r}; expected {expected!r}"
        )
    return expected


def _support_smoke_wrapper(source: Path, workdir: Path) -> Path:
    wrapper = workdir / "support_smoke_app.py"
    wrapper.write_text(
        f'''"""Release-smoke wrapper for the legacy multi-operation example."""
import sys

sys.path.append({str(source.parent)!r})

import app as example
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot.runtime import Runtime

turn = 0


def model_function(messages, info):
    global turn
    turn += 1
    calls = (
        ("load_customer", {{"customer_id": "customer-1"}}),
        ("load_policy", {{"topic": "outage"}}),
        (
            "create_ticket",
            {{
                "customer_id": "customer-1",
                "priority": "urgent",
                "summary": "Confirmed API outage",
            }},
        ),
    )
    if turn <= len(calls):
        name, arguments = calls[turn - 1]
        return ModelResponse(parts=[ToolCallPart(name, arguments)])
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {{
                    "ticket_id": "ticket-1-urgent",
                    "priority": "urgent",
                    "reply": "The outage is recorded without an invented ETA.",
                    "account_plan": "enterprise",
                }},
            )
        ]
    )


example.summon._runtime = Runtime(model=FunctionModel(model_function))
summon = example.summon
''',
        encoding="utf-8",
    )
    return wrapper


def _verify_case(case: ExampleCase, examples_root: Path, workdir: Path) -> None:
    source = (examples_root / case.source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    served_source = (
        _support_smoke_wrapper(source, workdir)
        if case.source == "06_support_service/app.py"
        else source
    )

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = _smoke_environment(
        SUMMONPOT_MODEL="test",
        SUMMONPOT_ORDER_LOG=str(workdir / "orders.jsonl"),
        SUMMONPOT_TICKET_LOG=str(workdir / "tickets.jsonl"),
    )
    process = subprocess.Popen(
        [
            _cli_path(),
            "serve",
            str(served_source),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=workdir,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until_ready(base_url, process)

        success, body = _request(base_url, case.method, case.path, payload=case.payload)
        if success != 200:
            raise AssertionError(f"{case.source} success returned {success}: {body!r}")
        json.loads(body)

        missing, _ = _request(base_url, "GET", "/__missing__")
        if missing != 404:
            raise AssertionError(f"{case.source} missing route returned {missing}")

        mismatch_method = "PUT" if case.method == "GET" else "GET"
        mismatch_path = urllib.parse.urlsplit(case.path).path
        mismatch, _ = _request(base_url, mismatch_method, mismatch_path)
        if mismatch != 405:
            raise AssertionError(f"{case.source} method mismatch returned {mismatch}")

        if case.method == "POST":
            invalid, _ = _request(base_url, "POST", case.path, payload={})
        else:
            invalid, _ = _request(
                base_url, "GET", "/products?max_price_cents=not-an-integer"
            )
        if invalid != 422:
            raise AssertionError(f"{case.source} invalid request returned {invalid}")

        if case.source == "basic_app.py":
            oversized, _ = _request(
                base_url, "POST", case.path, payload={"text": "x" * 2001}
            )
            if oversized != 422:
                raise AssertionError(
                    f"{case.source} oversized request returned {oversized}"
                )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples-root", type=Path, required=True)
    arguments = parser.parse_args()

    _verify_installed_version()

    with tempfile.TemporaryDirectory(prefix="summonpot-release-smoke-") as directory:
        workdir = Path(directory)
        for case in CASES:
            _verify_case(case, arguments.examples_root, workdir)

    print(f"verified {len(CASES)} example applications through the installed CLI")


if __name__ == "__main__":
    main()
