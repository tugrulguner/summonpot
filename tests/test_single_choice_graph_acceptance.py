"""Public acceptance for stable ordering, choice authority and compatibility."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot._execution import _compile_endpoint
from summonpot.contracts import ArgumentSource
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    n: int


class Value(BaseModel):
    n: int


class Candidate(BaseModel):
    n: int


class Response(BaseModel):
    total: int


def register(count=2, *, order=None, join=False, late_request=False, invalid=None):
    starts = []

    def root(n: int = 2) -> Value:
        starts.append("root")
        return Value(n=n + 1)

    first = Operation(root, bind={} if late_request else {"n": FromRequest("n")})

    def produce(n: int) -> list[Candidate]:
        starts.append("producer")
        return [Candidate(n=n + 4 + index * 5) for index in range(count)]

    producer = Operation(produce, bind={"n": FromRequest("n")})

    def helper(n: int) -> Value:
        starts.append("helper")
        return Value(n=n * 2)

    helper_op = Operation(helper, bind={"n": FromResult(first, "n")})

    def consume(candidate: Candidate, extra: int = 0) -> Value:
        starts.append("consumer")
        return Value(n=candidate.n + extra)

    source = producer
    if invalid == "foreign":
        source = Operation(produce, bind={"n": FromRequest("n")})
    bindings: dict[str, ArgumentSource] = {"candidate": AgentChoice(from_result=source)}
    if join:
        bindings["extra"] = FromResult(helper_op, "n")
    consumer = Operation(consume, bind=bindings)
    if invalid == "duplicate_callable_names":
        helper_op = Operation(
            consume,
            bind={"candidate": AgentChoice(from_result=producer)},
            after=(first,),
        )

    def finish(a: int, b: int) -> Response:
        starts.append("sink")
        return Response(total=a + b)

    sink = Operation(
        finish,
        bind={
            "a": FromRequest("n")
            if invalid == "multiple_sinks"
            else FromResult(helper_op, "n"),
            "b": FromResult(consumer, "n"),
        },
    )
    operations = {
        "root": first,
        "producer": producer,
        "helper": helper_op,
        "consumer": consumer,
        "sink": sink,
    }
    names = order or ("sink", "root", "producer", "consumer", "helper")
    markers = [Required(operations[name], calls=Exactly(1)) for name in names]
    app = Summon("graph-acceptance", runtime=Runtime(model="invalid:not-used"))

    @app("/run")
    def endpoint(
        request: Request,
        a=markers[0],
        b=markers[1],
        c=markers[2],
        d=markers[3],
        e=markers[4],
    ) -> Response:
        """Select an allowed current candidate and return the exact joined result."""
        ...

    return app, starts


def selector(calls, *, token_override=None):
    def choose(messages, info):
        assert not info.function_tools
        assert "Fixed endpoint goal" in info.instructions
        text = next(
            part.content
            for message in reversed(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        frontier = json.loads(text.splitlines()[-1])
        assert list(frontier) == ["decision_slot_0"]
        domain = frontier["decision_slot_0"]
        assert domain["argument"] == "candidate"
        assert len({x["token"] for x in domain["candidates"]}) == len(
            domain["candidates"]
        )
        chosen = domain["candidates"][-1]["token"]
        if token_override is not None:
            chosen = token_override(calls, chosen)
        calls.append(chosen)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"decision_slot_0": chosen})]
        )

    return FunctionModel(choose)


@pytest.mark.parametrize("join", [False, True])
@pytest.mark.parametrize("late_request", [False, True])
@pytest.mark.parametrize(
    "order",
    [
        ("sink", "root", "producer", "consumer", "helper"),
        ("sink", "consumer", "producer", "helper", "root"),
    ],
)
def test_graph_topology_and_declaration_order(join, late_request, order):
    app, starts = register(order=order, join=join, late_request=late_request)
    calls = []
    app._runtime = Runtime(model=selector(calls), retries=0)
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"n": 3})
    assert response.status_code == 200
    subtotal = 6 if late_request else 8
    assert response.json() == {"total": subtotal + 12 + (subtotal if join else 0)}
    if order[1] == "root":
        expected = (
            ["root", "producer", "helper", "consumer", "sink"]
            if join
            else ["root", "producer", "consumer", "helper", "sink"]
        )
    else:
        expected = (
            ["producer", "root", "helper", "consumer", "sink"]
            if join
            else ["producer", "consumer", "root", "helper", "sink"]
        )
    assert starts == expected
    assert len(calls) == 1


@pytest.mark.parametrize("count", [0, 129])
def test_unavailable_domain_stops_before_model_or_consumer(monkeypatch, count):
    app, starts = register(count=count)
    monkeypatch.setattr(
        Runtime,
        "model_for",
        lambda *a, **k: pytest.fail("unavailable domain resolved model"),
    )
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"n": 3})
    assert response.status_code == 409
    assert starts == ["root", "producer"]


def test_singleton_and_maximum_domain():
    for count in (1, 128):
        app, starts = register(count=count)
        calls = []
        app._runtime = Runtime(model=selector(calls), retries=0)
        with TestClient(build_app(app)) as client:
            response = client.post("/run", json={"n": 3})
        assert response.status_code == 200
        assert response.json() == {"total": 8 + 7 + (count - 1) * 5}
        assert len(calls) == (0 if count == 1 else 1)
        assert len(starts) == 5


@pytest.mark.parametrize("quota", [0, 1, 10])
def test_quota_changed_after_registration_rejects_before_effects(quota):
    app, starts = register()
    app._runtime.usage_limits = UsageLimits(tool_calls_limit=quota)
    with TestClient(build_app(app)) as client:
        response = client.post("/run", json={"n": 3})
    assert response.status_code == 500
    assert starts == []


def test_private_compatibility_compilation_rejects_new_shape():
    app, starts = register()
    with pytest.raises(TypeError, match="direct execution"):
        _compile_endpoint(app.endpoints[0], allow_direct=False)
    assert starts == []


@pytest.mark.parametrize(
    "invalid", ["foreign", "duplicate_callable_names", "multiple_sinks"]
)
def test_unsupported_graphs_still_reject_at_registration(invalid):
    with pytest.raises(TypeError):
        register(invalid=invalid)


@pytest.mark.parametrize("cross_request", [False, True])
def test_forged_or_other_request_token_never_starts_consumer(cross_request):
    app, starts = register()
    calls = []

    def override(history, valid):
        return (
            history[0]
            if cross_request and history
            else valid
            if cross_request
            else "not-a-current-token"
        )

    app._runtime = Runtime(model=selector(calls, token_override=override), retries=0)
    with TestClient(build_app(app)) as client:
        if cross_request:
            assert client.post("/run", json={"n": 3}).status_code == 200
            starts.clear()
        response = client.post("/run", json={"n": 3})
    assert response.status_code == 502
    assert starts == ["root", "producer"]
