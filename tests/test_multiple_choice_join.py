"""Public HTTP qualification for multi-choice join consumers."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Request(BaseModel):
    amount: int


class Candidate(BaseModel):
    code: str


class Output(BaseModel):
    left: str
    right: str


def make_app(events, *, left_values=None, right_values=None, mixed=False):
    def left_source(amount: int) -> list[Candidate]:
        events.append("left_source")
        return (
            left_values
            if left_values is not None
            else [Candidate(code="L1"), Candidate(code="L2")]
        )

    def right_source(amount: int) -> list[Candidate]:
        events.append("right_source")
        return (
            right_values
            if right_values is not None
            else [Candidate(code="R1"), Candidate(code="R2")]
        )

    left = Operation(
        left_source, bind={"amount": FromRequest("amount")}, output=list[Candidate]
    )
    right = Operation(
        right_source, bind={"amount": FromRequest("amount")}, output=list[Candidate]
    )

    def finish(first: Candidate, second: Candidate) -> Output:
        events.append(("finish", first, second))
        return Output(left=first.code, right=second.code)

    terminal = Operation(
        finish,
        bind={
            "first": AgentChoice(from_result=left),
            "second": AgentChoice(from_result=right),
        },
        output=Output,
    )

    def choose(messages, info):
        return select(messages, info, events)

    app = Summon(
        "multi-choice-join", runtime=Runtime(model=FunctionModel(choose), retries=0)
    )

    @app("/join")
    def endpoint(
        request: Request,
        result=Required(terminal, calls=Exactly(1)),
        left_result=Required(left, calls=Exactly(1)),
        right_result=Required(right, calls=Exactly(1)),
    ) -> Output:
        """Join two independently produced, permitted choices."""
        ...

    return app, left, right


def select(messages, info, events):
    assert not info.function_tools
    assert len(info.output_tools) == 1
    text = next(
        part.content
        for message in reversed(messages)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )
    frontier = json.loads(text.splitlines()[-1])
    arguments = tuple(domain["argument"] for domain in frontier.values())
    events.append(("selection", arguments))
    args = {
        slot: min(domain["candidates"], key=lambda item: item["value"]["code"])["token"]
        for slot, domain in frontier.items()
    }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])


def post(app):
    with TestClient(build_app(app)) as client:
        return client.post("/join", json={"amount": 3})


def test_two_ambiguous_domains_select_together_once_and_bind_canonical_members():
    events = []
    app, _, _ = make_app(events)
    response = post(app)
    assert response.status_code == 200
    assert response.json() == {"left": "L1", "right": "R1"}
    finished = [
        event for event in events if isinstance(event, tuple) and event[0] == "finish"
    ]
    assert len(finished) == 1
    assert type(finished[0][1]) is Candidate and type(finished[0][2]) is Candidate
    assert finished[0][1].code == "L1" and finished[0][2].code == "R1"
    assert [
        event
        for event in events
        if isinstance(event, tuple) and event[0] == "selection"
    ] == [("selection", ("first", "second"))]
    assert events.count("left_source") == events.count("right_source") == 1


def test_singleton_and_ambiguous_domain_requests_only_ambiguous_slot():
    events = []
    app, _, _ = make_app(events, left_values=[Candidate(code="L-only")])
    response = post(app)
    assert response.status_code == 200
    assert response.json() == {"left": "L-only", "right": "R1"}
    assert [
        event
        for event in events
        if isinstance(event, tuple) and event[0] == "selection"
    ] == [("selection", ("second",))]
    assert events.count("left_source") == events.count("right_source") == 1


def test_later_empty_domain_rejects_before_selection_or_join_after_producers_started(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        pytest.fail("Unavailable join domain resolved a model")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    events = []
    app, _, _ = make_app(events, right_values=[])
    response = post(app)
    assert response.status_code == 409
    assert response.json() == {
        "detail": "No supported candidate domain is available for the declared choice."
    }
    assert events == ["left_source", "right_source"]


def test_other_argument_token_cannot_authorize_the_join(monkeypatch):
    import sys

    calls = []

    def swapped(messages, info, events):
        assert not info.function_tools
        text = next(
            part.content
            for message in reversed(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        frontier = json.loads(text.splitlines()[-1])
        assert len(frontier) == 2
        wrong_token = next(iter(frontier.values()))["candidates"][0]["token"]
        calls.append(True)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, {slot: wrong_token for slot in frontier}
                )
            ]
        )

    monkeypatch.setattr(sys.modules[__name__], "select", swapped)
    events = []
    app, _, _ = make_app(events)
    response = post(app)
    assert response.status_code == 502
    assert calls == [True]
    assert events == ["left_source", "right_source"]
