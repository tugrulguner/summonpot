"""Stable resolved graphs reuse the guarded chain execution kernel."""

import asyncio
import time
from dataclasses import replace
from typing import Annotated

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from summonpot import (
    AgentChoice,
    Depends,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot._execution import _compile_endpoint
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    value: int


class Value(BaseModel):
    value: int


class Response(BaseModel):
    total: int


PositiveResponse = Annotated[Response, Field(description="Exact annotated response")]


def graph(events, *, outcome="success", reverse=False, unsupported=None):
    async def left(value: int):
        events.append(("left", value))
        if outcome == "failure":
            raise RuntimeError("private-secret-effect")
        if outcome == "invalid":
            return {"value": "private-secret-effect"}
        if outcome == "timeout":
            await asyncio.sleep(10)
        if outcome == "cancel":
            raise asyncio.CancelledError
        return Value(value=value + 1)

    def right(value: int):
        events.append(("right", value))
        return Value(value=value * 2)

    def helper(value: int, offset: int = 3):
        events.append(("helper", value))
        return Value(value=value + offset)

    def finish(a: Annotated[int, Field(gt=0)], b: int):
        events.append(("finish", a))
        if outcome == "terminal_invalid":
            return {"total": "private-secret-effect"}
        return Response(total=a + b)

    first = Operation(left, bind={"value": FromRequest("value")}, output=Value)
    second = Operation(right, bind={"value": FromRequest("value")}, output=Value)
    third = Operation(
        helper,
        bind={"value": FromResult(second, "value")},
        after=(first,),
        output=Value,
    )
    terminal = Operation(
        finish,
        bind={"a": FromResult(first, "value"), "b": FromResult(third, "value")},
        output=PositiveResponse,
    )
    if unsupported == "disconnected":
        object.__setattr__(third, "after", ())
        object.__setattr__(
            terminal,
            "bind",
            {"a": FromResult(first, "value"), "b": FromRequest("value")},
        )
    elif unsupported == "choice":
        object.__setattr__(second, "bind", {"value": AgentChoice()})
    elif unsupported == "final":
        object.__setattr__(
            third, "bind", {"value": FromResult(second, "value", invocation="final")}
        )
    elif unsupported == "cycle":
        object.__setattr__(first, "after", (terminal,))
    elif unsupported == "self":
        object.__setattr__(first, "after", (first,))
    elif unsupported == "foreign":
        object.__setattr__(first, "after", (Operation(right, output=Value),))
    elif unsupported == "ambiguous":
        object.__setattr__(second, "output", PositiveResponse)
        object.__setattr__(third, "bind", {"value": FromRequest("value")})
        object.__setattr__(third, "after", (first, second))
    elif unsupported == "annotation":
        object.__setattr__(terminal, "output", Response)
    elif unsupported == "mutable":
        helper.__defaults__ = ([],)
    app = Summon("graph", runtime=Runtime(model="invalid:provider", retries=4))
    if reverse:

        @app("/graph")
        def endpoint(
            request: Request,
            a=Required(first, calls=Exactly(1)),
            b=Required(second, calls=Exactly(1)),
            c=Required(third, calls=Exactly(1)),
            d=Required(terminal, calls=Exactly(1)),
        ) -> PositiveResponse:
            """Calculate both branches and their joined report."""
            ...
    else:

        @app("/graph")
        def endpoint(
            request: Request,
            d=Required(terminal, calls=Exactly(1)),
            c=Required(third, calls=Exactly(1)),
            b=Depends(second)
            if unsupported == "optional"
            else Required(second, calls=Exactly(1)),
            a=Required(first, calls=Exactly(1)),
        ) -> PositiveResponse:
            """Calculate both branches and their joined report."""
            ...

    return app


@pytest.fixture(autouse=True)
def forbid_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Resolved graphs must not resolve or construct models")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    monkeypatch.setattr(Runtime, "_agent_for", forbidden)


@pytest.mark.parametrize("reverse", [False, True])
def test_four_operations_control_edges_stable_order_and_provenance(reverse):
    events = []
    app = graph(events, reverse=reverse)
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"value": 5}))
    assert result == Response(total=19)
    branches = [("left", 5), ("right", 5)]
    assert events == (branches if reverse else branches[::-1]) + [
        ("helper", 10),
        ("finish", 6),
    ]


@pytest.mark.parametrize(
    "shape",
    [
        "disconnected",
        "choice",
        "final",
        "cycle",
        "self",
        "foreign",
        "ambiguous",
        "annotation",
        "mutable",
        "optional",
    ],
)
def test_unsupported_graphs_reject_before_any_start(shape):
    events = []
    match = "unique endpoint response producer" if shape == "ambiguous" else None
    with pytest.raises(TypeError, match=match):
        graph(events, unsupported=shape)
    assert events == []


def test_private_legacy_compilation_rejects_nonlinear_graph():
    events = []
    app = graph(events)
    with pytest.raises(TypeError, match="direct execution"):
        _compile_endpoint(app.endpoints[0], allow_direct=False)
    assert events == []


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("failure", 500),
        ("invalid", 502),
        ("terminal_invalid", 502),
        ("timeout", 504),
        ("success", 422),
    ],
)
def test_failures_stop_downstream_and_redact_http(outcome, status, caplog):
    events = []
    app = graph(events, outcome=outcome)
    if outcome == "timeout":
        app._runtime.timeout = 0.03
    value = -2 if status == 422 else 5
    with TestClient(build_app(app), raise_server_exceptions=False) as client:
        response = client.post("/graph", json={"value": value})
    assert response.status_code == status, response.text
    assert "private-secret-effect" not in response.text + caplog.text
    expected = [("right", value), ("left", value)]
    if status == 422 or outcome == "terminal_invalid":
        expected.append(("helper", value * 2))
    if outcome == "terminal_invalid":
        expected.append(("finish", value + 1))
    assert events == expected


def test_cancellation_does_not_replay_or_start_downstream():
    events = []
    app = graph(events, outcome="cancel")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app._runtime.call(app.endpoints[0], {"value": 5}))
    assert events == [("right", 5), ("left", 5)]


def test_metadata_is_frozen_and_requests_are_isolated():
    events = []
    app = graph(events)
    endpoint = app.endpoints[0]
    plan = app._runtime._plan_for(endpoint)
    for tool in endpoint.tools:
        if tool.name == "helper":
            tool.fn.__defaults__ = (1000,)
        tool.fn = lambda: pytest.fail("Mutable inspection metadata executed")
        tool.required = False
        tool.contract = None
    endpoint.tools.reverse()
    endpoint.output_annotation = Value
    assert app._runtime._plan_for(endpoint) is plan

    async def calls():
        return await asyncio.gather(
            *(app._runtime.call(endpoint, {"value": value}) for value in (2, 7))
        )

    assert asyncio.run(calls()) == [Response(total=10), Response(total=25)]
    for value in (2, 7):
        assert events.count(("left", value)) == events.count(("right", value)) == 1
        assert (
            events.count(("helper", value * 2))
            == events.count(("finish", value + 1))
            == 1
        )


def test_final_audit_obeys_deadline(monkeypatch):
    events = []
    app = graph(events)
    runtime = app._runtime
    runtime.timeout = 0.03
    plan = runtime._plan_for(app.endpoints[0])
    audit = plan.output_auditor
    assert audit is not None

    def slow_audit(value):
        time.sleep(0.06)
        return audit(value)

    monkeypatch.setattr(
        runtime, "_plan_for", lambda endpoint: replace(plan, output_auditor=slow_audit)
    )
    with pytest.raises(TimeoutError):
        asyncio.run(runtime.call(app.endpoints[0], {"value": 5}))
    assert [name for name, _ in events] == ["right", "left", "helper", "finish"]


@pytest.mark.parametrize("request_model", [False, True])
def test_nonlinear_graph_requires_request_model_and_request_binding(request_model):
    def left(value: int = 1) -> Value:
        return Value(value=value)

    def right(value: int = 2) -> Value:
        return Value(value=value)

    def finish(a: int, b: int) -> Response:
        return Response(total=a + b)

    first = Operation(
        left, bind={} if request_model else {"value": FromRequest("value")}
    )
    second = Operation(right, bind={})
    terminal = Operation(
        finish, bind={"a": FromResult(first, "value"), "b": FromResult(second, "value")}
    )
    app = Summon("ineligible")
    with pytest.raises(TypeError, match="Resolved graphs require"):
        if request_model:

            @app("/invalid")
            def with_model(
                request: Request,
                a=Required(first, calls=Exactly(1)),
                b=Required(second, calls=Exactly(1)),
                c=Required(terminal, calls=Exactly(1)),
            ) -> Response:
                """Require a real request binding."""
                ...
        else:

            @app("/invalid")
            def without_model(
                value: int,
                a=Required(first, calls=Exactly(1)),
                b=Required(second, calls=Exactly(1)),
                c=Required(terminal, calls=Exactly(1)),
            ) -> Response:
                """Require a Pydantic request."""
                ...


def test_many_vertices_use_exact_identity_and_current_ready_priority():
    from types import SimpleNamespace

    from summonpot._validation import (
        _chain_contract_tool_indices,
        _resolved_graph_tool_indices,
    )

    def identity(value: int) -> Value:
        return Value(value=value)

    roots = [
        Operation(identity, bind={"value": FromRequest("value")}, output=Value)
        for _ in range(7)
    ]
    # The same callable can occupy different graph vertices. A helper becomes
    # ready ahead of other roots and must win by current declaration priority.
    helper = Operation(
        identity, bind={"value": FromResult(roots[0], "value")}, output=Value
    )
    terminal = Operation(
        identity,
        bind={"value": FromResult(helper, "value")},
        after=tuple(roots),
        output=Response,
    )
    contracts = [terminal, helper, *roots]
    tools = [
        SimpleNamespace(contract=op, required=True, bounds=Exactly(1))
        for op in contracts
    ]
    assert _chain_contract_tool_indices(tools) is None
    assert _resolved_graph_tool_indices(tools) == (2, 1, 3, 4, 5, 6, 7, 8, 0)


def test_multiple_producer_choices_do_not_gain_nonlinear_admission():
    def candidates(value: int) -> list[Value]:
        return [Value(value=value)]

    def choose(item: Value) -> Value:
        return item

    def independent(item: Value) -> Value:
        return Value(value=item.value)

    def finish(a: int, b: int) -> Response:
        return Response(total=a + b)

    producer = Operation(candidates, bind={"value": FromRequest("value")})
    chosen = Operation(choose, bind={"item": AgentChoice(from_result=producer)})
    other = Operation(independent, bind={"item": AgentChoice(from_result=producer)})
    terminal = Operation(
        finish, bind={"a": FromResult(chosen, "value"), "b": FromResult(other, "value")}
    )
    app = Summon("choice-negative")
    with pytest.raises(TypeError, match="unenforced"):

        @app("/invalid")
        def endpoint(
            request: Request,
            a=Required(producer, calls=Exactly(1)),
            b=Required(chosen, calls=Exactly(1)),
            c=Required(other, calls=Exactly(1)),
            d=Required(terminal, calls=Exactly(1)),
        ) -> Response:
            """Do not widen the producer choice contract."""
            ...


def test_context_receivers_are_preflighted_before_any_graph_effect():
    from pydantic import ConfigDict

    from summonpot import FromContext
    from summonpot.runtime import _ContextError

    class Principal(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        level: int

    def authenticate(request) -> Principal:
        return Principal(level=2)

    events = []

    def left(value: int) -> Value:
        events.append("left")
        return Value(value=value)

    def right(value: int) -> Value:
        events.append("right")
        return Value(value=value)

    def finish(a: int, b: int, level: Annotated[int, Field(gt=1)]) -> Response:
        events.append("finish")
        return Response(total=a + b + level)

    first = Operation(left, bind={"value": FromRequest("value")})
    second = Operation(right, bind={"value": FromRequest("value")})
    terminal = Operation(
        finish,
        bind={
            "a": FromResult(first, "value"),
            "b": FromResult(second, "value"),
            "level": FromContext("level"),
        },
    )
    app = Summon("context-graph", context=authenticate)

    @app("/graph")
    def endpoint(
        request: Request,
        a=Required(first, calls=Exactly(1)),
        b=Required(second, calls=Exactly(1)),
        c=Required(terminal, calls=Exactly(1)),
    ) -> Response:
        """Preflight terminal context before independent effects."""
        ...

    runtime = Runtime()
    with pytest.raises(_ContextError):
        asyncio.run(
            runtime.call(app.endpoints[0], {"value": 3}, context=Principal(level=0))
        )
    assert events == []
    assert asyncio.run(
        runtime.call(app.endpoints[0], {"value": 3}, context=Principal(level=2))
    ) == Response(total=8)
    assert events == ["left", "right", "finish"]
