"""Registration and argument-namespace acceptance for bounded repetition."""

import asyncio
from typing import Literal

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_bounded_repeated_calls import Request, Snapshot, repeating_app, scripted

from summonpot import (
    AgentChoice,
    AtLeast,
    AtMost,
    Between,
    Exactly,
    FromRequest,
    Operation,
    Required,
    Summon,
)
from summonpot._execution import _register_endpoint
from summonpot.runtime import Runtime


@pytest.mark.parametrize("bounds", [Between(0, 3), AtMost(3)])
def test_required_marker_preserves_its_existing_positive_effective_minimum(bounds):
    events, callbacks = [], []
    app = repeating_app(events, bounds=bounds)
    result = asyncio.run(
        Runtime(
            model=scripted(
                [
                    {"decision": "finish"},
                    {"decision": "invoke", "argument_0": "stock"},
                    {"decision": "finish"},
                ],
                callbacks,
            )
        ).call(app.endpoints[0], {"audit_id": "a-1"})
    )
    assert result.checks == ["stock"] and events == ["stock"]
    assert len(callbacks) == 3


@pytest.mark.parametrize("bounds", [AtLeast(1)])
def test_unsupported_bound_shapes_rejected_before_execution(bounds):
    with pytest.raises(TypeError):
        repeating_app([], bounds=bounds)


@pytest.mark.parametrize("choice_type", [str, Literal[1, 2], Literal["stock", 1]])
def test_repeated_choice_requires_plain_finite_string_literals(choice_type):
    def operation(audit_id: str, check) -> Snapshot:
        raise AssertionError("registration never executes application")

    operation.__annotations__["check"] = choice_type
    op = Operation(
        operation,
        bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
        output=Snapshot,
    )
    with pytest.raises(TypeError):
        app = Summon("reject")

        @app("/reject")
        def endpoint(
            request: Request, result=Required(op, calls=Exactly(2))
        ) -> Snapshot:
            """Run the explicitly declared audit contract."""
            ...


def test_repeated_scalar_output_is_rejected_before_effects():
    def operation(audit_id: str, check: Literal["stock"]) -> str:
        raise AssertionError("registration never executes application")

    op = Operation(
        operation,
        bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
        output=str,
    )
    with pytest.raises(TypeError):
        app = Summon("reject-output")

        @app("/reject")
        def endpoint(request: Request, result=Required(op, calls=Exactly(2))) -> str:
            """Run the explicitly declared audit contract."""
            ...


def test_repeated_shape_does_not_turn_fully_bound_inputs_into_batch():
    def operation(audit_id: str) -> Snapshot:
        raise AssertionError("registration never executes application")

    op = Operation(
        operation, bind={"audit_id": FromRequest("audit_id")}, output=Snapshot
    )
    with pytest.raises(TypeError):
        app = Summon("reject-batch")

        @app("/reject")
        def endpoint(
            request: Request, result=Required(op, calls=Exactly(2))
        ) -> Snapshot:
            """Run the explicitly declared audit contract."""
            ...


def test_repeated_exact_response_annotation_is_required():
    class Other(BaseModel):
        value: str

    def operation(audit_id: str, check: Literal["stock"]) -> Snapshot:
        raise AssertionError("registration never executes application")

    op = Operation(
        operation,
        bind={"audit_id": FromRequest("audit_id"), "check": AgentChoice()},
        output=Snapshot,
    )
    with pytest.raises(TypeError):
        app = Summon("reject-response")

        @app("/reject")
        def endpoint(request: Request, result=Required(op, calls=Exactly(2))) -> Other:
            """Run the explicitly declared audit contract."""
            ...


def test_allow_direct_false_preserves_repeated_enforcement():
    events, callbacks = [], []
    app = repeating_app(events, bounds=Exactly(2))
    _register_endpoint(app.endpoints[0], allow_direct=False)
    result = asyncio.run(
        Runtime(
            model=scripted(
                [
                    {"decision": "invoke", "argument_0": "stock"},
                    {"decision": "invoke", "argument_0": "prices"},
                ],
                callbacks,
            )
        ).call(app.endpoints[0], {"audit_id": "a-1"})
    )
    assert result.checks == ["stock", "prices"] and events == ["stock", "prices"]
    assert len(callbacks) == 2


def test_business_arguments_cannot_collide_with_private_decision_fields():
    calls = []

    def operation(
        audit_id: str, decision: Literal["stock"], argument_0: Literal["prices"]
    ) -> Snapshot:
        calls.append((audit_id, decision, argument_0))
        return Snapshot(checks=[decision, argument_0])

    op = Operation(
        operation,
        bind={
            "audit_id": FromRequest("audit_id"),
            "decision": AgentChoice(),
            "argument_0": AgentChoice(),
        },
        output=Snapshot,
    )
    app = Summon("collisions")

    @app("/collisions")
    def endpoint(request: Request, result=Required(op, calls=Exactly(2))) -> Snapshot:
        """Run the explicitly declared audit contract."""
        ...

    def model(messages, info):
        assert not info.function_tools
        assert set(info.output_tools[0].parameters_json_schema["properties"]) == {
            "decision",
            "argument_0",
            "argument_1",
        }
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "decision": "invoke",
                        "argument_0": "stock",
                        "argument_1": "prices",
                    },
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"audit_id": "a-1"})
    )
    assert (
        result.checks == ["stock", "prices"]
        and calls == [("a-1", "stock", "prices")] * 2
    )
