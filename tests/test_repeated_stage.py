"""Public contract for final invocation addressing."""

from typing import Annotated, Any, Literal, cast

import pytest
from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelResponse, ToolCallPart
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


def producer():
    return None


def test_from_result_accepts_explicit_final_invocation():
    operation = Operation(producer)

    binding = FromResult(operation, "audit_id", invocation="final")

    assert binding.operation is operation
    assert binding.field == "audit_id"
    assert binding.invocation == "final"


@pytest.mark.parametrize("selector", ["latest", "first", 1, True, None])
def test_from_result_rejects_non_final_explicit_selector(selector):
    operation = Operation(producer)
    if selector is None:
        return
    with pytest.raises(ValueError, match="plain literal 'final'"):
        FromResult(operation, "audit_id", invocation=selector)


def test_final_invocation_selector_is_keyword_only():
    with pytest.raises(TypeError):
        cast(Any, FromResult)(Operation(producer), "audit_id", "final")


def test_existing_two_argument_from_result_remains_unqualified():
    operation = Operation(producer)

    binding = FromResult(operation, "audit_id")

    assert binding.invocation is None


class StageRequest(BaseModel):
    audit_id: str


class StageSnapshot(BaseModel):
    audit_id: str
    check: str


class StageReport(BaseModel):
    audit_id: str
    final_check: str


def stage_app(
    decisions,
    *,
    bounds=None,
    fail_at=None,
    runtime_options=None,
    terminal_failure=False,
    terminal_invalid=False,
    producer_delay: float = 0,
    terminal_delay: float = 0,
    check_constraint=False,
):
    events = []
    replies = iter(decisions)

    def inspect(audit_id: str, check: Literal["stock", "prices"]) -> StageSnapshot:
        events.append(("inspect", audit_id, check))
        if producer_delay:
            import time

            time.sleep(producer_delay)
        if fail_at == len(events):
            raise ValueError("application failure")
        return StageSnapshot(audit_id=audit_id, check=check)

    def report(audit_id: str, check: str) -> StageReport:
        events.append(("report", audit_id, check))
        if terminal_failure:
            raise ValueError("terminal application failure")
        if terminal_invalid:
            return cast(Any, {"invalid": True})
        if terminal_delay:
            import time

            time.sleep(terminal_delay)
        return StageReport(audit_id=audit_id, final_check=check)

    if check_constraint:
        report.__annotations__["check"] = Annotated[str, Field(min_length=6)]

    def choose(messages, info):
        assert not info.function_tools
        assert all(event[0] != "report" for event in events)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(replies))]
        )

    runtime = Runtime(model=FunctionModel(choose), retries=0, **(runtime_options or {}))
    inspect_op = Operation(
        inspect,
        bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
        output=StageSnapshot,
    )
    report_op = Operation(
        report,
        bind={
            "audit_id": FromResult(inspect_op, "audit_id", invocation="final"),
            "check": FromResult(inspect_op, "check", invocation="final"),
        },
        output=StageReport,
    )
    app = Summon("stage-report", runtime=runtime)

    @app("/audit")
    def endpoint(
        request: StageRequest,
        checks=Required(inspect_op, calls=bounds or Between(1, 3)),
        final=Required(report_op, calls=Exactly(1)),
    ) -> StageReport:
        """Perform bounded inspections, then report the final completed stage result."""
        ...

    return app, runtime, events


def test_closed_stage_consumes_second_snapshot_and_runs_terminal_once():
    app, runtime, events = stage_app(
        [
            {"decision": "invoke", "argument_0": "stock"},
            {"decision": "invoke", "argument_0": "prices"},
            {"decision": "finish"},
        ]
    )
    import asyncio

    result = asyncio.run(runtime.call(app.endpoints[0], {"audit_id": "audit-1"}))
    assert result == StageReport(audit_id="audit-1", final_check="prices")
    assert events == [
        ("inspect", "audit-1", "stock"),
        ("inspect", "audit-1", "prices"),
        ("report", "audit-1", "prices"),
    ]
