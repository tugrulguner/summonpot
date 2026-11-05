from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "benchmark_progression.py"
SPEC = importlib.util.spec_from_file_location("benchmark_progression", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_choice_fixture_executes_actual_producer_and_one_selection():
    import asyncio

    workload = benchmark.make_workload("choice")
    result = asyncio.run(
        workload.runtime.call(workload.app.endpoints[0], workload.body)
    )
    assert result.model_dump(mode="json") == workload.expected
    assert workload.starts == ["options", "selected"]
    assert len(workload.model_calls) == 1


def test_percentile_uses_nearest_rank():
    assert benchmark.percentile([1, 2, 3, 4, 5], 0.95) == 5


def test_gate_blocks_latency_or_semantic_regressions():
    result = benchmark.evaluate_gate(
        {
            "median_ns": 111,
            "p95_ns": 100,
            "model_calls": 1,
            "operation_starts": 2,
            "failures": 0,
        },
        {
            "median_ns": 100,
            "p95_ns": 100,
            "model_calls": 1,
            "operation_starts": 2,
            "failures": 0,
        },
        threshold=0.10,
    )
    assert not result["passed"]
    assert result["median_regression"] == pytest.approx(0.11)


def test_gate_requires_equal_calls_and_zero_failures():
    result = benchmark.evaluate_gate(
        {
            "median_ns": 90,
            "p95_ns": 90,
            "model_calls": 2,
            "operation_starts": 2,
            "failures": 0,
        },
        {
            "median_ns": 100,
            "p95_ns": 100,
            "model_calls": 1,
            "operation_starts": 2,
            "failures": 0,
        },
        threshold=0.10,
    )
    assert not result["passed"]
    assert "model_calls" in result["reasons"]


def test_gate_blocks_explicit_semantic_failure_even_with_equal_counts():
    base = {
        "median_ns": 100,
        "p95_ns": 100,
        "model_calls": 0,
        "operation_starts": 1,
        "semantic_verified": True,
    }
    candidate = {**base, "semantic_verified": False}
    assert not benchmark.evaluate_gate(candidate, base)["passed"]
