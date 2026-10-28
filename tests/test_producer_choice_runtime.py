"""Runtime authority for producer-backed candidate selections."""

import asyncio

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime


@pytest.fixture(autouse=True)
def preserve_agent_choice_protocol_coverage(monkeypatch):
    """Keep historical agent adversaries on the agent compatibility executor."""
    import summonpot._execution as execution

    compile_endpoint = execution._compile_endpoint

    def agent_plan(endpoint, **kwargs):
        kwargs["allow_direct"] = False
        return compile_endpoint(endpoint, **kwargs)

    monkeypatch.setattr(execution, "_compile_endpoint", agent_plan)


class Request(BaseModel):
    query: str


class Candidate(BaseModel):
    identifier: str
    label: str


class Receipt(BaseModel):
    identifier: str


def choice_app(events, *, candidates=None):
    canonical = (
        candidates
        if candidates is not None
        else [
            Candidate(identifier="A", label="first"),
            Candidate(identifier="B", label="second"),
        ]
    )

    def find(query: str) -> list[Candidate]:
        events.append(("find", query))
        return canonical

    producer = Operation(
        find, bind={"query": FromRequest("query")}, output=list[Candidate]
    )

    def reserve(item: Candidate) -> Receipt:
        events.append(("reserve", item))
        return Receipt(identifier=item.identifier)

    consumer = Operation(
        reserve, bind={"item": AgentChoice(from_result=producer)}, output=Receipt
    )
    app = Summon("choice")

    @app("/choose")
    def endpoint(
        request: Request,
        found=Required(producer, calls=Exactly(1)),
        reserved=Required(consumer, calls=Exactly(1)),
    ) -> Receipt:
        """Find candidates and reserve the best declared option."""
        ...

    return app, canonical


def test_model_selects_token_and_operation_receives_canonical_item():
    events = []
    app, canonical = choice_app(events)
    advertised = []

    def model(messages, info):
        names = [tool.name for tool in info.function_tools]
        advertised.append(names)
        if names == ["find"]:
            return ModelResponse(parts=[ToolCallPart("find", {})])
        if names == ["reserve"]:
            schema = info.function_tools[0].parameters_json_schema
            field = schema["properties"]["item"]
            assert field["type"] == "string"
            assert len(field["enum"]) == 2
            assert "second" in info.function_tools[0].description
            return ModelResponse(
                parts=[ToolCallPart("reserve", {"item": field["enum"][1]})]
            )
        return ModelResponse(parts=[TextPart("invented receipt")])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(
            app.endpoints[0], {"query": "notebook"}
        )
    )
    assert result == Receipt(identifier="B")
    assert events[0] == ("find", "notebook")
    assert events[1][0] == "reserve"
    assert events[1][1] == canonical[1]
    assert type(events[1][1]) is Candidate
    assert advertised == [["find"], ["reserve"], []]


def test_empty_candidates_fail_before_another_model_request():
    events = []
    app, _ = choice_app(events, candidates=[])
    requests = []

    def model(messages, info):
        requests.append([tool.name for tool in info.function_tools])
        return ModelResponse(parts=[ToolCallPart("find", {})])

    with pytest.raises(RuntimeError, match="candidate"):
        asyncio.run(
            Runtime(model=FunctionModel(model)).call(
                app.endpoints[0], {"query": "empty"}
            )
        )
    assert requests == [["find"]]
    assert events == [("find", "empty")]


def test_membership_is_exact_request_local_and_canonical_identity():
    from pydantic_ai import ModelRetry

    from summonpot._execution import _new_run, _prepare_request
    from summonpot.runtime import _ensure_choice_sets, _invoke_bound_operation

    events = []
    app, _ = choice_app(events)
    plan = Runtime(model="test")._plan_for(app.endpoints[0])

    async def exercise():
        left = _new_run(plan, _prepare_request(plan, {"query": "left"}))
        right = _new_run(plan, _prepare_request(plan, {"query": "right"}))
        for run in (left, right):
            await _invoke_bound_operation(plan.tools[0], run, {})
            async with run.lock:
                _ensure_choice_sets(plan.tools[1], run, plan.tools)
        token, canonical, _ = left.choice_sets[(1, "item")][1]
        assert canonical is left.states[0].result[1]
        for invalid in (token, "forged", True, {"identifier": "B", "label": "second"}):
            with pytest.raises(ModelRetry):
                await _invoke_bound_operation(plan.tools[1], right, {"item": invalid})
        assert right.states[1].started == 0
        result = await _invoke_bound_operation(plan.tools[1], left, {"item": token})
        assert result.identifier == "B"
        assert events[-1][1] is canonical
        with pytest.raises(ModelRetry):
            await _invoke_bound_operation(plan.tools[1], left, {"item": token})
        assert left.states[1].started == 1

    asyncio.run(exercise())


def test_model_forged_token_never_starts_consumer():
    from pydantic_ai import UnexpectedModelBehavior

    events = []
    app, _ = choice_app(events)

    def model(messages, info):
        name = info.function_tools[0].name
        return ModelResponse(
            parts=[ToolCallPart(name, {} if name == "find" else {"item": "forged"})]
        )

    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(
            Runtime(model=FunctionModel(model), retries=0).call(
                app.endpoints[0], {"query": "safe"}
            )
        )
    assert events == [("find", "safe")]


def test_empty_candidate_http_is_redacted_conflict():
    from fastapi.testclient import TestClient

    from summonpot.server import build_app

    events = []
    app, _ = choice_app(events, candidates=[])
    count = []

    def model(messages, info):
        count.append(1)
        return ModelResponse(parts=[ToolCallPart("find", {})])

    app._runtime = Runtime(model=FunctionModel(model))
    with TestClient(build_app(app)) as client:
        response = client.post("/choose", json={"query": "secret-query"})
    assert response.status_code == 409
    assert response.json() == {
        "detail": "No supported candidate domain is available for the declared choice."
    }
    assert count == [1]
    assert events == [("find", "secret-query")]


@pytest.mark.parametrize("oversize", ["count", "evidence"])
def test_oversized_candidate_domain_fails_before_decision(oversize):
    from summonpot.runtime import _ChoiceUnavailableError

    events = []
    candidates = (
        [Candidate(identifier=str(index), label="x") for index in range(129)]
        if oversize == "count"
        else [Candidate(identifier="A", label="x" * 65536)]
    )
    app, _ = choice_app(events, candidates=candidates)
    count = []

    def model(messages, info):
        count.append(1)
        return ModelResponse(parts=[ToolCallPart("find", {})])

    with pytest.raises(_ChoiceUnavailableError):
        asyncio.run(
            Runtime(model=FunctionModel(model)).call(
                app.endpoints[0], {"query": "oversize"}
            )
        )
    assert count == [1]
    assert events == [("find", "oversize")]


def test_equal_candidates_remain_distinct_tokens_without_value_membership():
    from summonpot._execution import _new_run, _prepare_request
    from summonpot.runtime import _ensure_choice_sets, _invoke_bound_operation

    events = []
    app, _ = choice_app(
        events,
        candidates=[
            Candidate(identifier="same", label="same"),
            Candidate(identifier="same", label="same"),
        ],
    )
    plan = Runtime(model="test")._plan_for(app.endpoints[0])

    async def exercise():
        run = _new_run(plan, _prepare_request(plan, {"query": "duplicates"}))
        await _invoke_bound_operation(plan.tools[0], run, {})
        async with run.lock:
            _ensure_choice_sets(plan.tools[1], run, plan.tools)
        choices = run.choice_sets[(1, "item")]
        assert choices[0][0] != choices[1][0]
        await _invoke_bound_operation(plan.tools[1], run, {"item": choices[1][0]})
        assert events[-1][1] is run.states[0].result[1]

    asyncio.run(exercise())


def test_candidate_projection_uses_aliases_excludes_secrets_and_never_serializes():
    from pydantic import Field, field_serializer

    calls = []

    class PrivateCandidate(BaseModel):
        identifier: str = Field(serialization_alias="publicId")
        secret: str = Field(exclude=True)

        @field_serializer("identifier")
        def serializer(self, value):
            calls.append("serializer")
            raise AssertionError("candidate serializers must not execute")

        def __eq__(self, other):
            calls.append("equality")
            raise AssertionError("candidate equality is not membership authority")

    def find(query: str):
        return [PrivateCandidate(identifier="safe", secret="hidden-secret")]

    producer = Operation(
        find, bind={"query": FromRequest("query")}, output=list[PrivateCandidate]
    )
    observed = []

    def reserve(item: PrivateCandidate):
        observed.append(item.identifier)
        return Receipt(identifier=item.identifier)

    consumer = Operation(
        reserve, bind={"item": AgentChoice(from_result=producer)}, output=Receipt
    )
    app = Summon("private-candidates")

    @app("/choose")
    def endpoint(
        request: Request,
        found=Required(producer, calls=Exactly(1)),
        reserved=Required(consumer, calls=Exactly(1)),
    ) -> Receipt:
        """Select one allowed item."""
        ...

    def model(messages, info):
        if not info.function_tools:
            return ModelResponse(parts=[TextPart("done")])
        tool = info.function_tools[0]
        if tool.name == "find":
            return ModelResponse(parts=[ToolCallPart("find", {})])
        assert '"publicId": "safe"' in tool.description
        assert "hidden-secret" not in tool.description
        assert '"secret"' not in tool.description
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "reserve",
                    {
                        "item": tool.parameters_json_schema["properties"]["item"][
                            "enum"
                        ][0]
                    },
                )
            ]
        )

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"query": "safe"})
    )
    assert result.identifier == "safe"
    assert observed == ["safe"]
    assert calls == []


def test_concurrent_public_requests_have_disjoint_choice_tokens():
    events = []
    app, _ = choice_app(events)
    domains = []

    def model(messages, info):
        if not info.function_tools:
            return ModelResponse(parts=[TextPart("done")])
        tool = info.function_tools[0]
        if tool.name == "find":
            return ModelResponse(parts=[ToolCallPart("find", {})])
        tokens = tool.parameters_json_schema["properties"]["item"]["enum"]
        domains.append(tuple(tokens))
        return ModelResponse(parts=[ToolCallPart("reserve", {"item": tokens[0]})])

    runtime = Runtime(model=FunctionModel(model))

    async def exercise():
        return await asyncio.gather(
            *(
                runtime.call(app.endpoints[0], {"query": f"run-{index}"})
                for index in range(12)
            )
        )

    results = asyncio.run(exercise())
    assert all(result.identifier == "A" for result in results)
    assert len(domains) == 12
    assert len({token for domain in domains for token in domain}) == 24
    assert sum(event[0] == "reserve" for event in events) == 12
