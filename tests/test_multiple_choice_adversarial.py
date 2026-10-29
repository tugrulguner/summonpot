"""Boundary regressions for multiple-choice local prefixes and one-way handoff."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import _register_endpoint
from summonpot.runtime import Runtime, _ChoiceUnavailableError
from summonpot.server import build_app


class Input(BaseModel):
    query: str


class Item(BaseModel):
    key: str


class Result(BaseModel):
    key: str


def staged_chain(counts, events, received=None):
    def find(query: str) -> list[Item]:
        events.append("find")
        return [Item(key=f"{query}-{i}") for i in range(counts[0])]

    operations = [
        Operation(find, bind={"query": FromRequest("query")}, output=list[Item])
    ]

    def intermediate(index):
        def step(item: Item) -> list[Item]:
            events.append(f"step{index}")
            if received is not None:
                received.append(item)
            return [Item(key=f"{item.key}-{i}") for i in range(counts[index])]

        step.__name__ = f"step{index}"
        return step

    for index in range(1, len(counts)):
        operations.append(
            Operation(
                intermediate(index),
                bind={"item": AgentChoice(from_result=operations[-1])},
                output=list[Item],
            )
        )

    def finish(item: Item) -> Result:
        events.append("finish")
        if received is not None:
            received.append(item)
        return Result(key=item.key)

    operations.append(
        Operation(
            finish,
            bind={"item": AgentChoice(from_result=operations[-1])},
            output=Result,
        )
    )
    app = Summon("staged")
    required = [Required(op, calls=Exactly(1)) for op in operations]
    # Capability parameters are finite declarations, not public runtime selectors.
    if len(required) == 3:

        @app("/staged")
        def endpoint(
            request: Input, a=required[0], b=required[1], c=required[2]
        ) -> Result:
            """Select each candidate and finish."""
            ...
    else:
        assert len(required) == 4

        @app("/staged")
        def longer(
            request: Input, a=required[0], b=required[1], c=required[2], d=required[3]
        ) -> Result:
            """Select each of three candidates and finish."""
            ...

    return app


def scripted(events, rounds):
    def model(messages, info):
        names = [tool.name for tool in info.function_tools]
        rounds.append(names)
        events.append("model")
        if not names:
            return ModelResponse(parts=[TextPart("forged final result")])
        assert len(names) == 1
        tool = info.function_tools[0]
        args = {
            key: field["enum"][0]
            for key, field in tool.parameters_json_schema["properties"].items()
        }
        return ModelResponse(parts=[ToolCallPart(tool.name, args)])

    return FunctionModel(model)


@pytest.mark.parametrize("counts", [(1, 1), (1, 1, 1), (1, 2), (2, 1), (2, 2)])
def test_frontiers_preserve_one_way_handoff_and_exact_starts(monkeypatch, counts):
    events, rounds, received, runs = [], [], [], []
    app = staged_chain(counts, events, received)
    import summonpot.runtime as module

    original_new = module._new_run

    def capture(*args):
        run = original_new(*args)
        runs.append(run)
        return run

    monkeypatch.setattr(module, "_new_run", capture)
    original = Runtime.model_for

    def resolution(runtime, endpoint):
        events.append("resolve")
        return original(runtime, endpoint)

    monkeypatch.setattr(Runtime, "model_for", resolution)
    result = asyncio.run(
        Runtime(model=scripted(events, rounds)).call(app.endpoints[0], {"query": "Q"})
    )
    assert result.key == "Q-0" + "-0" * (len(counts) - 1)
    assert events.count("find") == 1 and events.count("finish") == 1
    for index in range(1, len(counts)):
        assert events.count(f"step{index}") == 1
    for index, value in enumerate(received):
        assert value is runs[0].states[index].result[0]
    if 2 not in counts:
        assert not rounds and "resolve" not in events
    else:
        frontier = counts.index(2)
        expected_prefix = ["find"] + [f"step{i}" for i in range(1, frontier + 1)]
        assert events[: events.index("resolve")] == expected_prefix
        assert events.count("resolve") == 1
        expected_suffix = [f"step{i}" for i in range(frontier + 1, len(counts))] + [
            "finish"
        ]
        assert rounds == [[name] for name in expected_suffix] + [[]]


def dual_app(events, first, second, reverse=False):
    def find(query: str) -> list[Item]:
        events.append("find")
        return [Item(key=f"A-{i}") for i in range(first)]

    a = Operation(find, bind={"query": FromRequest("query")}, output=list[Item])

    def other(query: str) -> list[Item]:
        events.append("other")
        if second == -1:
            return [Item(key="x" * 65536)]
        return [Item(key=f"B-{i}") for i in range(second)]

    b = Operation(
        other, bind={"query": FromRequest("query")}, output=list[Item], after=(a,)
    )

    def finish(left: Item, right: Item) -> Result:
        events.append("finish")
        return Result(key=left.key + right.key)

    bindings = {"left": AgentChoice(from_result=a), "right": AgentChoice(from_result=b)}
    if reverse:
        bindings = dict(reversed(list(bindings.items())))
    c = Operation(finish, bind=bindings, output=Result)
    app = Summon("dual")

    @app("/dual")
    def endpoint(
        request: Input,
        a=Required(a, calls=Exactly(1)),
        b=Required(b, calls=Exactly(1)),
        c=Required(c, calls=Exactly(1)),
    ) -> Result:
        """Choose both arguments and finish."""
        ...

    return app


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("second", [0, 129, -1])
def test_all_current_domains_reject_before_model_in_either_binding_order(
    monkeypatch, reverse, second
):
    events = []
    app = dual_app(events, 2, second, reverse)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid domain must precede model entry")

    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    with TestClient(build_app(app)) as client:
        response = client.post("/dual", json={"query": "q"})
    assert response.status_code == 409
    assert events == ["find", "other"]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("counts", [(1, 1), (1, 2), (2, 1), (128, 1)])
def test_same_consumer_domains_accept_locally_or_handoff_once(reverse, counts):
    events, rounds = [], []
    app = dual_app(events, counts[0], counts[1], reverse)
    result = asyncio.run(
        Runtime(model=scripted(events, rounds)).call(app.endpoints[0], {"query": "q"})
    )
    assert result.key == "A-0B-0"
    assert events.count("finish") == 1
    assert rounds == ([] if counts == (1, 1) else [["finish"], []])


@pytest.mark.parametrize("first", [1, 2])
def test_later_empty_domain_keeps_prior_effects_and_model_history(first):
    events, rounds = [], []
    app = staged_chain((first, 0), events)
    with pytest.raises(_ChoiceUnavailableError):
        asyncio.run(
            Runtime(model=scripted(events, rounds)).call(
                app.endpoints[0], {"query": "q"}
            )
        )
    assert events.count("find") == 1 and events.count("step1") == 1
    assert "finish" not in events
    assert bool(rounds) is (first == 2)


def test_cross_argument_token_cannot_authorize_consumer():
    events = []
    app = dual_app(events, 2, 2)
    attempts = []

    def model(messages, info):
        if not info.function_tools:
            return ModelResponse(parts=[TextPart("done")])
        fields = info.function_tools[0].parameters_json_schema["properties"]
        assert set(fields["left"]["enum"]).isdisjoint(fields["right"]["enum"])
        attempts.append(tuple(fields["left"]["enum"]))
        args = {"left": fields["right"]["enum"][0], "right": fields["right"]["enum"][0]}
        return ModelResponse(parts=[ToolCallPart("finish", args)])

    with TestClient(build_app(app)) as client:
        app._runtime = Runtime(model=FunctionModel(model))
        response = client.post("/dual", json={"query": "q"})
    assert response.status_code == 502
    assert len(attempts) >= 2 and all(a == attempts[0] for a in attempts)
    assert events == ["find", "other"]


def test_compatibility_plan_runs_all_operations_through_agent():
    events, rounds = [], []
    app = staged_chain((1, 1), events)
    _register_endpoint(app.endpoints[0], allow_direct=False)
    result = asyncio.run(
        Runtime(model=scripted(events, rounds)).call(app.endpoints[0], {"query": "q"})
    )
    assert result.key == "q-0-0"
    assert rounds == [["find"], ["step1"], ["finish"], []]


def test_cached_agent_does_not_force_a_later_all_singleton_request(monkeypatch):
    events, rounds = [], []
    counts = [1, 2]
    app = staged_chain(counts, events)
    runtime = Runtime(model=scripted(events, rounds))
    asyncio.run(runtime.call(app.endpoints[0], {"query": "warm"}))
    assert runtime._agents
    counts[1] = 1

    def forbidden(*args, **kwargs):
        raise AssertionError("warm cached agent must remain unused")

    for name in ("model_for", "_agent_for", "_build_agent"):
        monkeypatch.setattr(Runtime, name, forbidden)
    result = asyncio.run(runtime.call(app.endpoints[0], {"query": "cold"}))
    assert result.key == "cold-0-0"


def test_shared_runtime_requests_have_disjoint_tokens_and_exact_effects():
    events, rounds, domains = [], [], []
    app = staged_chain((1, 2), events)
    base_model = scripted(events, rounds)

    def model(messages, info):
        if info.function_tools:
            domains.append(
                set(
                    info.function_tools[0].parameters_json_schema["properties"]["item"][
                        "enum"
                    ]
                )
            )
        assert base_model.function is not None
        return base_model.function(messages, info)

    runtime = Runtime(model=FunctionModel(model))

    async def run_all():
        return await asyncio.gather(
            *(runtime.call(app.endpoints[0], {"query": str(i)}) for i in range(8))
        )

    results = asyncio.run(run_all())
    assert {r.key for r in results} == {f"{i}-0-0" for i in range(8)}
    assert len(domains) == 8 and len(set.union(*domains)) == 16
    assert events.count("find") == events.count("step1") == events.count("finish") == 8
