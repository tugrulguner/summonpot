#!/usr/bin/env python3
"""Matched CPU-only regression benchmark for unchanged Summonpot paths.

Run under either checkout's environment with its own ``PYTHONPATH=src``. The
same CLI emits JSONL raw request timings and semantic counters; paired mode
launches the selected base and candidate interpreters in alternating order.
Application state is in-memory Python only, identically initialized per trial;
no SQLite or provider/network work is included in the timed workload. HTTP is
real localhost Uvicorn/FastAPI. The choices use Pydantic AI FunctionModel.
"""

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal


def percentile(values: list[int], quantile: float) -> int:
    """Nearest-rank percentile (one-indexed), without interpolation."""
    if not values:
        raise ValueError("percentile requires at least one observation")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, int((len(ordered) * quantile + 0.999999999) // 1) - 1)]


def summarize(values: list[int]) -> dict[str, int | float]:
    return {
        "median_ns": int(statistics.median(values)),
        "p95_ns": percentile(values, 0.95),
    }


def evaluate_gate(
    candidate: dict[str, Any], base: dict[str, Any], threshold: float = 0.10
) -> dict[str, Any]:
    median = candidate["median_ns"] / base["median_ns"] - 1
    p95 = candidate["p95_ns"] / base["p95_ns"] - 1
    reasons = []
    for key in ("model_calls", "operation_starts"):
        if candidate[key] != base[key]:
            reasons.append(key)
    if candidate.get("failures", 0) or base.get("failures", 0):
        reasons.append("failures")
    if (
        candidate.get("semantic_verified") is False
        or base.get("semantic_verified") is False
    ):
        reasons.append("semantic_failure")
    if median > threshold:
        reasons.append("median_latency")
    if p95 > threshold:
        reasons.append("p95_latency")
    return {
        "passed": not reasons,
        "median_regression": median,
        "p95_regression": p95,
        "reasons": reasons,
    }


@dataclass
class Workload:
    app: Any
    runtime: Any
    body: dict[str, Any]
    expected: dict[str, Any]
    starts: list[str]
    model_calls: list[str]


def make_workload(name: str) -> Workload:
    from pydantic import BaseModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel

    from summonpot import (
        AgentChoice,
        Between,
        Exactly,
        FromRequest,
        FromResult,
        Operation,
        Required,
        Summon,
    )
    from summonpot.runtime import Runtime

    starts: list[str] = []
    model_calls: list[str] = []

    class Req(BaseModel):
        value: int

    class First(BaseModel):
        value: int

    class Final(BaseModel):
        value: int
        path: str

    class Option(BaseModel):
        value: int

    def first(value: int) -> First:
        starts.append("first")
        return First(value=value + 1)

    first_op = Operation(first, bind={"value": FromRequest("value")}, output=First)

    def finish(value: int) -> Final:
        starts.append("finish")
        return Final(value=value, path=name)

    finish_op = Operation(
        finish, bind={"value": FromResult(first_op, "value")}, output=Final
    )

    def options(value: int) -> list[Option]:
        starts.append("options")
        return [Option(value=value + 1), Option(value=value + 2)]

    producer = Operation(
        options, bind={"value": FromRequest("value")}, output=list[Option]
    )

    def selected(option: Option) -> Final:
        starts.append("selected")
        return Final(value=option.value, path=name)

    selected_op = Operation(
        selected, bind={"option": AgentChoice(from_result=producer)}, output=Final
    )

    def model_callback(messages: Any, info: Any) -> Any:
        assert not info.function_tools, "benchmark must use framework-owned progression"
        model_calls.append(name)
        prompt = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        assert isinstance(prompt, str)
        if name == "choice":
            data = json.loads(prompt[prompt.index('{"decision_slot_') :])
            arguments = {
                slot: domain["candidates"][0]["token"] for slot, domain in data.items()
            }
        elif name == "repeat":
            data = json.loads(prompt)
            arguments = (
                {"decision": "invoke", "argument_0": "left"}
                if data["starts"] < 2
                else {"decision": "finish"}
            )
        else:
            raise AssertionError("resolved benchmark unexpectedly requested inference")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, arguments)])

    runtime = Runtime(model=FunctionModel(model_callback), retries=0)
    app = Summon("benchmark-" + name, runtime=runtime)
    if name == "direct":

        @app("/bench/direct")
        def endpoint(
            request: Req, result=Required(first_op, calls=Exactly(1))
        ) -> First:
            """Resolve one direct operation."""
            ...

        body, expected = {"value": 7}, {"value": 8}
    elif name == "chain":

        @app("/bench/chain")
        def endpoint(
            request: Req,
            a=Required(first_op, calls=Exactly(1)),
            b=Required(finish_op, calls=Exactly(1)),
        ) -> Final:
            """Resolve the exact two-operation chain."""
            ...

        body, expected = {"value": 7}, {"value": 8, "path": name}
    elif name == "choice":

        @app("/bench/choice")
        def endpoint(
            request: Req,
            a=Required(producer, calls=Exactly(1)),
            b=Required(selected_op, calls=Exactly(1)),
        ) -> Final:
            """Select the first permitted value from canonical producer evidence."""
            ...

        body, expected = {"value": 7}, {"value": 8, "path": name}
    elif name == "repeat":

        def repeated(value: int, option: Literal["left", "right"]) -> First:
            starts.append("repeated")
            return First(value=value + (1 if option == "left" else 2))

        repeated_op = Operation(
            repeated,
            bind={"value": FromRequest("value"), "option": AgentChoice()},
            output=First,
        )

        @app("/bench/repeat")
        def endpoint(
            request: Req, result=Required(repeated_op, calls=Between(1, 3))
        ) -> First:
            """Invoke left twice and then finish the bounded work."""
            ...

        body, expected = {"value": 7}, {"value": 8}
    else:
        raise ValueError("unknown benchmark workload")
    return Workload(app, runtime, body, expected, starts, model_calls)


def _serve(workload: Workload) -> tuple[Any, threading.Thread, int]:
    import socket

    import uvicorn

    from summonpot.server import build_app

    http_app = build_app(workload.app)

    @http_app.get("/_benchmark/metrics")
    def metrics() -> dict[str, Any]:
        return {
            "ok": True,
            "application_starts": len(workload.starts),
            "model_calls": len(workload.model_calls),
        }

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        http_app, host="127.0.0.1", port=port, log_level="error", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/_benchmark/metrics", timeout=1
            ) as response:
                if response.status == 200:
                    return server, thread, port
        except Exception:
            time.sleep(0.02)
    server.should_exit = True
    thread.join(5)
    raise RuntimeError("localhost server failed readiness health check")


def run_trial(args: argparse.Namespace) -> dict[str, Any]:
    workload = make_workload(args.workload)
    server = thread = None
    port = None
    concurrency = getattr(args, "concurrency", 1)
    if args.transport == "http":
        server, thread, port = _serve(workload)
    endpoint = workload.app.endpoints[0]

    async def measured() -> dict[str, Any]:
        import httpx

        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:

            async def invoke():
                if args.transport == "runtime":
                    value = await workload.runtime.call(endpoint, dict(workload.body))
                    return value.model_dump(mode="json")
                response = await client.post(
                    f"http://127.0.0.1:{port}{endpoint.path}", json=workload.body
                )
                response.raise_for_status()
                return response.json()

            for _ in range(args.warmup):
                assert await invoke() == workload.expected
            workload.starts.clear()
            workload.model_calls.clear()

            async def one(index):
                async with semaphore:
                    start = time.perf_counter_ns()
                    try:
                        value = await invoke()
                        return time.perf_counter_ns() - start, value, None
                    except Exception as exc:
                        return (
                            time.perf_counter_ns() - start,
                            None,
                            {"request": index, "error_type": type(exc).__name__},
                        )

            begin = time.perf_counter_ns()
            rows = await asyncio.gather(*(one(i) for i in range(args.count)))
            batch_ns = time.perf_counter_ns() - begin
            latencies = [r[0] for r in rows]
            results = [r[1] for r in rows if r[2] is None]
            failures = [r[2] for r in rows if r[2] is not None]
            semantic_ok = len(results) == args.count and all(
                value == workload.expected for value in results
            )
            expected_starts = {
                "direct": {"first": 1},
                "chain": {"first": 1, "finish": 1},
                "choice": {"options": 1, "selected": 1},
                "repeat": {"repeated": 2},
            }[args.workload]
            expected_models = {"direct": 0, "chain": 0, "choice": 1, "repeat": 3}[
                args.workload
            ]
            counts = {
                key: workload.starts.count(key) for key in sorted(set(workload.starts))
            }
            counters_ok = (
                counts
                == {key: number * args.count for key, number in expected_starts.items()}
                and len(workload.model_calls) == expected_models * args.count
            )
            remote_counters = None
            if args.transport == "http":
                remote = (
                    await client.get(f"http://127.0.0.1:{port}/_benchmark/metrics")
                ).json()
                remote_counters = remote
                counters_ok = (
                    counters_ok
                    and remote["application_starts"] == len(workload.starts)
                    and remote["model_calls"] == len(workload.model_calls)
                )
            return {
                "schema": 2,
                "trial": args.trial,
                "source": source_identity(),
                "python": platform.python_version(),
                "versions": package_versions(),
                "workload": args.workload,
                "transport": args.transport,
                "concurrency": concurrency,
                "requests": args.count,
                "warmup": args.warmup,
                "raw_latency_ns": latencies,
                "batch_time_ns": batch_ns,
                "throughput_rps": args.count / (batch_ns / 1e9),
                "latency": summarize(latencies),
                "semantic_verified": semantic_ok and counters_ok,
                "counter_verified": counters_ok,
                "verified_results": len(results),
                "application_starts": len(workload.starts),
                "model_calls": len(workload.model_calls),
                "start_counts": counts,
                "model_call_counts": {args.workload: len(workload.model_calls)},
                "remote_counters": remote_counters,
                "failures": failures,
            }

    try:
        return asyncio.run(measured())
    finally:
        if server is not None:
            assert thread is not None
            server.should_exit = True
            thread.join(10)
            if thread.is_alive():
                raise RuntimeError("benchmark HTTP server did not shut down")


def _canonical(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def source_identity() -> dict[str, str]:
    try:
        import subprocess
        from pathlib import Path

        import summonpot

        root = str(Path(summonpot.__file__).resolve().parents[2])
        commit = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        tree = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD^{tree}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", root, "status", "--porcelain"], text=True
        ).strip()
        return {
            "commit": commit,
            "tree": tree,
            "dirty": "yes" if dirty else "no",
            "module": str(summonpot.__file__),
        }
    except Exception:
        return {"commit": "unknown", "tree": "unknown"}


def package_versions() -> dict[str, str]:
    result = {}
    for package in ("summonpot", "pydantic", "pydantic-ai-slim", "fastapi", "uvicorn"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "not-installed"
    return result


def paired(args: argparse.Namespace) -> None:
    command_common = [
        "--workload",
        args.workload,
        "--transport",
        args.transport,
        "--count",
        str(args.count),
        "--warmup",
        str(args.warmup),
        "--concurrency",
        str(args.concurrency),
    ]
    rows = []
    for trial in range(1, args.trials + 1):
        order = [
            ("base", args.base_python, args.base_path),
            ("candidate", args.candidate_python, args.candidate_path),
        ]
        if trial % 2 == 0:
            order.reverse()
        for side, interpreter, path in order:
            cmd = [
                interpreter,
                os.path.abspath(__file__),
                "single",
                *command_common,
                "--trial",
                str(trial),
            ]
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            env.pop("VIRTUAL_ENV", None)
            env["PYTHONPATH"] = os.path.join(path, "src")
            proc = subprocess.run(
                cmd, cwd=path, env=env, text=True, capture_output=True
            )
            if proc.returncode:
                rows.append(
                    {"side": side, "trial": trial, "process_error": proc.stderr[-1000:]}
                )
            else:
                row = json.loads(proc.stdout)
                row["side"] = side
                rows.append(row)
            print(json.dumps(rows[-1], sort_keys=True), flush=True)
    by_side = {
        side: [
            row for row in rows if row.get("side") == side and "raw_latency_ns" in row
        ]
        for side in ("base", "candidate")
    }
    complete = (
        len(by_side["base"]) == args.trials and len(by_side["candidate"]) == args.trials
    )
    if complete:

        def aggregate(side: str) -> dict[str, Any]:
            records = by_side[side]
            timings = [item for row in records for item in row["raw_latency_ns"]]
            return {
                **summarize(timings),
                "model_calls": sum(row["model_calls"] for row in records),
                "operation_starts": sum(row["application_starts"] for row in records),
                "failures": sum(len(row["failures"]) for row in records),
                "semantic_verified": all(row["semantic_verified"] for row in records),
            }

        base_summary, candidate_summary = aggregate("base"), aggregate("candidate")
        gate = evaluate_gate(candidate_summary, base_summary)
        gate["passed"] = (
            gate["passed"]
            and complete
            and base_summary["semantic_verified"]
            and candidate_summary["semantic_verified"]
        )
    else:
        base_summary = candidate_summary = None
        gate = {"passed": False, "reasons": ["incomplete_campaign"]}
    print(
        json.dumps(
            {
                "paired_campaign": True,
                "workload": args.workload,
                "transport": args.transport,
                "paired_trials": args.trials,
                "base_summary": base_summary,
                "candidate_summary": candidate_summary,
                "gate": gate,
                "rows": rows,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    single = sub.add_parser("single")
    paired_parser = sub.add_parser(
        "paired", help="run 5 alternating paired trials and retain every raw result"
    )
    for target in (single, paired_parser):
        target.add_argument(
            "--workload", choices=("direct", "chain", "choice", "repeat"), required=True
        )
        target.add_argument("--transport", choices=("runtime", "http"), required=True)
        target.add_argument("--count", type=int, default=1000)
        target.add_argument("--warmup", type=int, default=100)
        target.add_argument("--concurrency", type=int, choices=(1, 8), default=1)
    single.add_argument("--trial", type=int, default=1)
    paired_parser.add_argument("--trials", type=int, default=5)
    paired_parser.add_argument("--base-python", required=True)
    paired_parser.add_argument("--base-path", required=True)
    paired_parser.add_argument("--candidate-python", required=True)
    paired_parser.add_argument("--candidate-path", required=True)
    args = parser.parse_args()
    if args.count < 1 or args.warmup < 0:
        parser.error("count must be positive and warmup nonnegative")
    if args.mode == "single":
        print(json.dumps(run_trial(args), sort_keys=True))
    else:
        paired(args)


if __name__ == "__main__":
    main()
