"""Launch every documented example through the installed Summonpot CLI."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import secrets
import shutil
import socket
import sqlite3
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
        "05_bounded_runtime.py",
        "POST",
        "/summaries/fast",
        {"text": "Summonpot keeps endpoint authority bounded.", "max_sentences": 2},
    ),
    ExampleCase(
        "04_http_methods.py",
        "POST",
        "/products",
        {"customer_id": "smoke-customer", "sku": "notebook"},
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
    ExampleCase(
        "10_result_chain/app.py",
        "POST",
        "/reservations",
        {"sku": "notebook", "quantity": 2, "idempotency_key": "smoke-10"},
    ),
    ExampleCase(
        "11_linear_result_chain/app.py",
        "POST",
        "/reservations",
        {"sku": "notebook", "quantity": 2, "idempotency_key": "smoke-11"},
    ),
    ExampleCase(
        "12_producer_choice/app.py",
        "POST",
        "/orders",
        {
            "query": "blue notebook",
            "order_id": "smoke-12",
            "idempotency_key": "smoke-12",
        },
    ),
    ExampleCase(
        "13_multiple_producer_choices/app.py",
        "POST",
        "/orders",
        {"category": "coffee", "quantity": 1, "idempotency_key": "smoke-order"},
    ),
    ExampleCase(
        "13_authenticated_context/app.py",
        "POST",
        "/notes",
        {"note_id": "smoke", "text": "persisted note", "idempotency_key": "smoke-key"},
    ),
    ExampleCase(
        "14_bounded_audit/app.py",
        "POST",
        "/audits",
        {"audit_id": "smoke-audit"},
    ),
    ExampleCase(
        "15_repeated_stage/app.py", "POST", "/audits", {"audit_id": "smoke-stage"}
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
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    data = None
    headers = dict(headers or {})
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


def _bounded_audit_smoke_wrapper(source: Path, workdir: Path) -> Path:
    """Use real repeated runtime with a keyless, decision-only provider fixture."""
    wrapper = workdir / "bounded_audit_smoke_app.py"
    wrapper.write_text(
        f"""import sys,json
sys.path.append({str(source.parent)!r})
import app as example
from pydantic_ai.messages import ModelResponse,ModelRequest,UserPromptPart,ToolCallPart
from pydantic_ai.models.function import FunctionModel
from summonpot.runtime import Runtime

def choose(messages,info):
    assert not info.function_tools
    assert len(info.output_tools)==1
    assert set(info.output_tools[0].parameters_json_schema['properties'])=={{'decision','argument_0'}}
    prompts=[p.content for m in messages if isinstance(m,ModelRequest) for p in m.parts if isinstance(p,UserPromptPart) and isinstance(p.content,str)]
    starts=json.loads(prompts[0])['starts']
    payload={{'decision':'invoke','argument_0':('stock','prices')[starts]}} if starts<2 else {{'decision':'finish'}}
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,payload)])
example.summon._runtime=Runtime(model=FunctionModel(choose))
summon=example.summon
""",
        encoding="utf-8",
    )
    return wrapper


def _fixture_smoke_wrapper(
    source: Path, workdir: Path, payload: dict[str, Any] | None
) -> Path:
    """Keep model-only routes keyless and copy real catalog receipts, never invent them."""
    wrapper = workdir / "fixture_smoke_app.py"
    wrapper.write_text(
        f"""import importlib.util,sys,json
from pydantic_ai.messages import ModelResponse,ModelRequest,ToolReturnPart,ToolCallPart
from pydantic_ai.models.function import FunctionModel
from summonpot.runtime import Runtime
spec=importlib.util.spec_from_file_location('smoke_example',{str(source)!r})
example=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=example
spec.loader.exec_module(example)
payload={payload!r}
def model(messages,info):
    if {source.name!r}=='05_bounded_runtime.py':
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{{'summary':'Keyless contract fixture.','key_points':['The configured HTTP contract completed.']}})])
    results=[p.content for m in messages if isinstance(m,ModelRequest) for p in m.parts if isinstance(p,ToolReturnPart) and p.tool_name=='reserve_product']
    if not results:
        return ModelResponse(parts=[ToolCallPart('reserve_product',{{'customer_id':payload['customer_id'],'sku':payload['sku']}})])
    result=results[-1]
    if isinstance(result,str):result=json.loads(result)
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,result)])
fixture=FunctionModel(model)
class FixtureRuntime(Runtime):
    def model_for(self,endpoint):
        return fixture
prior=example.summon._runtime
example.summon._runtime=FixtureRuntime(retries=prior.retries,usage_limits=prior.usage_limits,timeout=prior.timeout)
summon=example.summon
""",
        encoding="utf-8",
    )
    return wrapper


def _verify_case(
    case: ExampleCase, examples_root: Path, workdir: Path
) -> dict[str, Any]:
    source = (examples_root / case.source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    served_source = (
        _support_smoke_wrapper(source, workdir)
        if case.source == "06_support_service/app.py"
        else _bounded_audit_smoke_wrapper(source, workdir)
        if case.source in {"14_bounded_audit/app.py", "15_repeated_stage/app.py"}
        else _fixture_smoke_wrapper(source, workdir, case.payload)
        if case.source == "05_bounded_runtime.py"
        or (case.source == "04_http_methods.py" and case.method == "POST")
        else source
    )

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = _smoke_environment(
        SUMMONPOT_MODEL="test",
        SUMMONPOT_ORDER_LOG=str(workdir / "orders.jsonl"),
        SUMMONPOT_TICKET_LOG=str(workdir / "tickets.jsonl"),
        INVENTORY_DB=str(workdir / "inventory.sqlite3"),
    )
    auth_headers: dict[str, str] = {}
    if case.source in {
        "08_direct_execution.py",
        "09_contract_boundaries/app.py",
        "10_result_chain/app.py",
        "11_linear_result_chain/app.py",
        "12_producer_choice/app.py",
    }:
        environment["SUMMONPOT_MODEL"] = "invalid:no-provider"
    if case.source == "14_bounded_audit/app.py":
        environment["BOUNDED_AUDIT_DB"] = str(workdir / "bounded-audit.sqlite3")
    if case.source == "15_repeated_stage/app.py":
        environment["REPEATED_STAGE_DB"] = str(workdir / "repeated-stage.sqlite3")
    if case.source == "13_multiple_producer_choices/app.py":
        environment.update(
            MULTIPLE_CHOICE_DB=str(workdir / "multiple-choice.sqlite3"),
            SUMMONPOT_MODEL="invalid:no-provider",
        )
    if case.source == "13_authenticated_context/app.py":
        token = secrets.token_urlsafe(32)
        environment.update(
            TENANT_BEARER_TOKENS=f"smoke-tenant:{token}",
            AUTH_CONTEXT_DB=str(workdir / "authenticated-notes.sqlite3"),
            SUMMONPOT_MODEL="invalid:no-provider",
        )
        auth_headers["Authorization"] = f"Bearer {token}"
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

        success, body = _request(
            base_url, case.method, case.path, payload=case.payload, headers=auth_headers
        )
        if success != 200:
            raise AssertionError(f"{case.source} success returned {success}: {body!r}")
        response_body = json.loads(body)
        side_effects: list[str] = []
        if case.source == "15_repeated_stage/app.py":
            with sqlite3.connect(environment["REPEATED_STAGE_DB"]) as db:
                reports = db.execute(
                    "SELECT report_json FROM audit_reports WHERE audit_id=?",
                    ("smoke-stage",),
                ).fetchall()
                checks = db.execute(
                    "SELECT check_name FROM audit_checks WHERE audit_id=? ORDER BY check_name",
                    ("smoke-stage",),
                ).fetchall()
            assert len(reports) == 1 and json.loads(reports[0][0]) == response_body
            assert checks == [("prices",), ("stock",)]
            assert (
                response_body["checks"] == ["prices", "stock"]
                and response_body["finding_count"] == 2
            )
            side_effects.append(
                "closed repeated stage and canonical persisted terminal report"
            )
        if case.source in {"10_result_chain/app.py", "11_linear_result_chain/app.py"}:
            assert case.payload is not None
            with sqlite3.connect(environment["INVENTORY_DB"]) as db:
                db.row_factory = sqlite3.Row
                receipt = dict(
                    db.execute(
                        "SELECT * FROM reservations WHERE idempotency_key=?",
                        (case.payload["idempotency_key"],),
                    ).fetchone()
                )
                assert receipt == response_body
                assert (
                    db.execute(
                        "SELECT available FROM inventory WHERE sku='notebook'"
                    ).fetchone()[0]
                    == response_body["remaining"]
                    == 23
                )
            side_effects.append("canonical SQLite reservation and exact stock")
        if case.source == "12_producer_choice/app.py":
            with sqlite3.connect(environment["INVENTORY_DB"]) as db:
                row = db.execute(
                    "SELECT item_id,remaining_stock FROM orders WHERE order_id='smoke-12'"
                ).fetchone()
                assert (
                    row == ("B", 11) and response_body["candidate"]["identifier"] == "B"
                )
                assert db.execute(
                    "SELECT stock FROM inventory WHERE item_id='B'"
                ).fetchone() == (11,)
            side_effects.append("singleton canonical SQLite order")
        if case.source == "13_multiple_producer_choices/app.py":
            with sqlite3.connect(environment["MULTIPLE_CHOICE_DB"]) as db:
                rows = db.execute(
                    "SELECT product_id,delivery_id,quantity,total_cents,remaining_stock FROM orders WHERE idempotency_key=?",
                    ("smoke-order",),
                ).fetchall()
                stock = db.execute(
                    "SELECT stock FROM products WHERE product_id='coffee'"
                ).fetchone()
            if len(rows) != 1 or rows[0][0:3] != ("coffee", "coffee-ground", 1):
                raise AssertionError(f"SQLite receipt mismatch: {rows!r}")
            if rows[0][3:] != (350, 4) or stock != (4,):
                raise AssertionError(
                    f"SQLite stock/total mismatch: {rows!r}, {stock!r}"
                )

        if auth_headers:
            denied, _ = _request(base_url, case.method, case.path, payload=case.payload)
            assert denied == 401
            repeat, repeated_body = _request(
                base_url,
                case.method,
                case.path,
                payload=case.payload,
                headers=auth_headers,
            )
            assert repeat == 200 and repeated_body == body
            with sqlite3.connect(environment["AUTH_CONTEXT_DB"]) as db:
                rows = db.execute(
                    "SELECT tenant_id,note_id,text,idempotency_key FROM notes"
                ).fetchall()
            assert rows == [("smoke-tenant", "smoke", "persisted note", "smoke-key")]

        missing, _ = _request(base_url, "GET", "/__missing__")
        if missing != 404:
            raise AssertionError(f"{case.source} missing route returned {missing}")

        mismatch_method = "PUT"
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
        with socket.socket() as listener:
            if listener.connect_ex(("127.0.0.1", port)) == 0:
                raise AssertionError(f"owned listener {port} remains open")
    return {
        "source": case.source,
        "method": case.method,
        "path": case.path,
        "status": success,
        "body": response_body,
        "invalid_status": invalid,
        "missing_status": missing,
        "method_mismatch_status": mismatch,
        "side_effects": side_effects,
        "listener_closed": True,
        "lane": "keyless contract fixture or explicit no-model path; not live-provider quality",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples-root", type=Path, required=True)
    parser.add_argument(
        "--report", type=Path, help="Write actual HTTP acceptance results as JSON"
    )
    arguments = parser.parse_args()
    import summonpot

    version = _verify_installed_version()
    applications = {case.source for case in CASES}
    discovered = {
        path.relative_to(arguments.examples_root).as_posix()
        for path in arguments.examples_root.rglob("*.py")
        if path.parent == arguments.examples_root or path.name == "app.py"
    }
    if applications != discovered:
        raise AssertionError(
            f"example verifier inventory mismatch: {applications ^ discovered}"
        )
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="summonpot-release-smoke-") as directory:
        for index, case in enumerate(CASES):
            workdir = Path(directory) / f"case-{index}"
            workdir.mkdir()
            results.append(_verify_case(case, arguments.examples_root, workdir))
            if arguments.report is not None:
                arguments.report.parent.mkdir(parents=True, exist_ok=True)
                arguments.report.write_text(
                    json.dumps(
                        {
                            "version": version,
                            "module_path": summonpot.__file__,
                            "cli": _cli_path(),
                            "application_count": len(applications),
                            "route_count": len(CASES),
                            "cases": results,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
    print(
        f"verified {len(applications)} example applications ({len(CASES)} HTTP routes) through the installed CLI"
    )


if __name__ == "__main__":
    main()
