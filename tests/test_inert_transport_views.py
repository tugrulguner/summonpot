"""Compatibility projections must never execute application hooks."""

from typing import Annotated, Any

import pytest
from fastapi.testclient import TestClient
from pydantic import AfterValidator, BaseModel, PlainSerializer
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import (
    _prepare_request,
    _registered_plan,
    _validated_transport_request,
)
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Result(BaseModel):
    value: int


def query_service(annotation: Any, received: list[Any]) -> Summon:
    def apply(value: int) -> Result:
        received.append(value)
        return Result(value=3)

    turns = 0

    def model(messages, info):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("apply", {})])
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"value": 3})]
        )

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("inert-transport")
    summon._runtime = Runtime(model=FunctionModel(model))

    @summon("/value", method="GET")
    def endpoint(
        value: annotation,  # type: ignore[valid-type]  # pyright: ignore[reportInvalidTypeForm]
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Use the authoritative value."""
        ...

    return summon


@pytest.mark.parametrize("raises", [False, True])
def test_query_public_views_never_call_str(raises):
    hooks = []

    class Value:
        def __init__(self, value):
            self.value = value

        def __str__(self):
            hooks.append("str")
            self.value = 999
            if raises:
                raise RuntimeError("application str")
            return "changed"

    received = []
    summon = query_service(Annotated[int, AfterValidator(Value)], received)
    response = TestClient(build_app(summon), raise_server_exceptions=False).get(
        "/value", params={"value": "3"}
    )
    assert response.status_code == 200, response.text
    assert received[0].value == 3
    assert hooks == []


def test_query_public_views_never_call_declared_serializer():
    hooks = []

    def serialize(value):
        hooks.append("serialize")
        value.append(999)
        return value

    received = []
    summon = query_service(
        Annotated[
            int, AfterValidator(lambda value: [value]), PlainSerializer(serialize)
        ],
        received,
    )
    response = TestClient(build_app(summon)).get("/value", params={"value": "3"})
    assert response.status_code == 200, response.text
    assert received == [[3]]
    assert hooks == []


def test_query_nested_public_value_cannot_mutate_operation_input(monkeypatch):
    class Value:
        def __init__(self, value):
            self.value = value

    received = []
    summon = query_service(
        Annotated[int, AfterValidator(lambda value: [Value(value)])], received
    )
    original = summon._runtime.call

    async def tamper(endpoint, params):
        nested = params.typed["value"][0]
        if type(nested) is Value:
            nested.value = 999
        else:
            params.typed["value"][0] = 999
        return await original(endpoint, params)

    monkeypatch.setattr(summon._runtime, "call", tamper)
    response = TestClient(build_app(summon)).get("/value", params={"value": "3"})
    assert response.status_code == 200, response.text
    assert received[0][0].value == 3


def test_projection_rejects_custom_metaclasses_without_comparison():
    hooks = []

    class Meta(type):
        def __eq__(cls, other):
            hooks.append("eq")
            raise RuntimeError("type equality hook")

    class Value(metaclass=Meta):
        pass

    from summonpot._execution import _public_transport_views

    summon = query_service(int, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    prompt, typed = _public_transport_views(
        plan, {"value": Value()}, {"value": Value()}
    )
    assert prompt == typed == {"value": "<unavailable>"}
    assert hooks == []


def test_projection_does_not_serialize_nested_models():
    from pydantic import field_serializer

    from summonpot._execution import _public_transport_views

    hooks = []

    class HostileModelMeta(type(BaseModel)):
        def __getattribute__(cls, name):
            if name == "model_fields":
                hooks.append("metaclass getattribute")
                raise RuntimeError("metaclass getattribute")
            return super().__getattribute__(name)

    class Value(BaseModel, metaclass=HostileModelMeta):
        items: list[int]

        @field_serializer("items")
        def serialize(self, value):
            hooks.append("serializer")
            value.append(999)
            raise RuntimeError("serializer")

    value = Value(items=[3])
    summon = query_service(int, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    nested = {"list": [value], "tuple": (value,), "dict": {"item": value}}
    prompt, typed = _public_transport_views(plan, {"value": nested}, {"value": nested})
    expected = {
        "list": [{"items": [3]}],
        "tuple": [{"items": [3]}],
        "dict": {"item": {"items": [3]}},
    }
    assert prompt == {"value": expected}
    assert typed == {"value": {**expected, "tuple": ({"items": [3]},)}}
    assert value.items == [3]
    assert hooks == []


@pytest.mark.parametrize("container_type", [set, frozenset])
def test_native_hashed_container_projection_falls_back_without_model_hooks(
    container_type,
):
    from pydantic import field_serializer

    from summonpot._execution import _public_transport_views

    hooks = []

    class Value(BaseModel):
        model_config = {"frozen": True}

        x: int

        @field_serializer("x")
        def serialize(self, value):
            hooks.append("serializer")
            raise RuntimeError("serializer")

        def __getattribute__(self, name):
            hooks.append("getattribute")
            raise RuntimeError("getattribute")

        def __repr__(self):
            hooks.append("repr")
            raise RuntimeError("repr")

        def __eq__(self, other):
            hooks.append("eq")
            raise RuntimeError("eq")

        def __hash__(self):
            hooks.append("hash")
            return 0

    value = Value.model_construct(x=3)
    container = container_type([value])
    hooks.clear()
    summon = query_service(int, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None

    prompt, typed = _public_transport_views(
        plan, {"value": container}, {"value": container}
    )

    assert prompt == {"value": [{"x": 3}]}
    assert typed == {"value": "<unavailable>"}
    assert hooks == []


def test_projection_bounds_deep_nesting():
    from summonpot._execution import _public_transport_views

    value: Any = 3
    for _ in range(1000):
        value = [value]
    summon = query_service(int, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    prompt, typed = _public_transport_views(plan, {"value": value}, {"value": value})
    for view in (prompt, typed):
        node = view["value"]
        for _ in range(63):
            assert type(node) is list
            node = node[0]
        assert node == "<unavailable>"


def test_projection_is_a_detached_inert_tree():
    import json

    hooks = []

    class Dangerous:
        def __str__(self):
            hooks.append("str")
            raise RuntimeError("str")

        def __repr__(self):
            hooks.append("repr")
            raise RuntimeError("repr")

    class DangerousList(list):
        def __iter__(self):
            hooks.append("iter")
            raise RuntimeError("iter")

    class DangerousDict(dict):
        def items(self):
            hooks.append("items")
            raise RuntimeError("items")

    class DangerousStr(str):
        def __str__(self):
            hooks.append("str subclass")
            raise RuntimeError("str subclass")

    item = Dangerous()
    cycle = []
    cycle.append(cycle)
    shared = [3]
    value = {
        "nested": [item, {"leaf": item}],
        "subclasses": [DangerousList([3]), DangerousDict(a=3), DangerousStr("x")],
        "cycle": cycle,
        "keys": {item: 3, 4: 5, "safe": 6},
        "floats": [float("nan"), float("inf"), -float("inf"), 1.5],
        "shared": [shared, shared],
        "tuple": (True, None, 3, "text"),
    }
    summon = query_service(int, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    carrier = _validated_transport_request(
        plan, {"value": value}, typed={"value": value}
    )
    expected = {
        "nested": ["<unavailable>", {"leaf": "<unavailable>"}],
        "subclasses": ["<unavailable>"] * 3,
        "cycle": ["<unavailable>"],
        "keys": {"safe": 6},
        "floats": ["<unavailable>"] * 3 + [1.5],
        "shared": [[3], [3]],
        "tuple": [True, None, 3, "text"],
    }
    assert carrier["value"] == expected
    native_expected = {**expected, "tuple": (True, None, 3, "text")}
    assert carrier.typed["value"] == native_expected
    json.dumps(dict(carrier), allow_nan=False)
    carrier["value"]["shared"][0].append(7)
    assert carrier["value"]["shared"][1] == [3]
    assert carrier.typed["value"] == native_expected
    prepared = _prepare_request(plan, carrier)
    assert prepared["value"] == expected
    assert prepared.typed["value"] is value
    assert shared == [3]
    assert hooks == []
