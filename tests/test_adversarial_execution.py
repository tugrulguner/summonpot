"""Regression probes for direct-execution trust boundaries."""

import asyncio
import threading
from typing import Any

import pytest
from pydantic import AliasPath, BaseModel, Field, RootModel, model_serializer

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import _registered_plan
from summonpot.runtime import Runtime, _OperationOutputError


class SelfCopyingMutable:
    def __init__(self) -> None:
        self.values: list[int] = []

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        return self


@pytest.mark.parametrize("wrapped", [False, True])
def test_mutable_self_copying_default_is_not_direct_eligible(wrapped: bool):
    state = SelfCopyingMutable()
    default = (state,) if wrapped else state

    def operation(value: int, state: Any = default) -> Request:
        return Request(value=value)

    summon = Summon("test")

    @summon("/defaults")
    def endpoint(
        request: Request,
        result=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=Request),
            calls=Exactly(1),
        ),
    ) -> Request:
        """Keep mutable defaults on the agent path."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    assert plan.direct_tool is None


@pytest.mark.parametrize("default", [threading.Lock(), object()])
def test_scalar_endpoint_defaults_keep_registration_and_identity(default: Any):
    summon = Summon("test")

    @summon("/scalar")
    def endpoint(value: Any = default) -> Request:
        """Keep scalar default semantics unchanged."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    assert plan.parameters[0].default is default
    assert plan.direct_tool is None
    summon.endpoints[0].parameters[0].default = "replacement"
    assert plan.parameters[0].default is default

    from summonpot.server import build_app

    route = next(route for route in build_app(summon).routes if route.path == "/scalar")
    request_model = route.endpoint.__annotations__["body"]
    assert request_model.model_fields["value"].default is default


class MutableInt(int):
    def __init__(self, value: int) -> None:
        self.values: list[int] = []


@pytest.mark.parametrize("default", [MutableInt(1), lambda: None, SelfCopyingMutable])
def test_nonbuiltin_default_objects_are_not_direct_eligible(default: Any):
    def operation(value: int, state: Any = default) -> Request:
        return Request(value=value)

    summon = Summon("test")

    @summon("/nonbuiltin-default")
    def endpoint(
        request: Request,
        result=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=Request),
            calls=Exactly(1),
        ),
    ) -> Request:
        """Keep unknown default state off the direct executor."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    assert plan.direct_tool is None


@pytest.mark.parametrize(
    "default", [None, True, 2, 1.5, 1j, "text", b"bytes", (1, "x"), frozenset({1})]
)
def test_builtin_immutable_defaults_remain_direct_and_identity_stable(default: Any):
    def operation(value: int, state: Any = default) -> Request:
        assert state is default
        return Request(value=value)

    summon = Summon("test")

    @summon("/immutable")
    def endpoint(
        request: Request,
        result=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=Request),
            calls=Exactly(1),
        ),
    ) -> Request:
        """Preserve supported default values."""
        ...

    assert (
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        ).value
        == 7
    )


def test_scalar_from_request_endpoint_stays_agent_backed():
    def operation(value: int) -> Request:
        return Request(value=value)

    summon = Summon("test")

    @summon("/scalar-bound")
    def endpoint(
        value: int,
        result=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=Request),
            calls=Exactly(1),
        ),
    ) -> Request:
        """Scalar fields do not activate the direct path."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    assert plan.direct_tool is None


class Request(BaseModel):
    value: int


class Response(BaseModel):
    value: int = Field(alias="externalValue")

    @model_serializer
    def launder(self) -> dict[str, int]:
        return {"externalValue": 42}


class StrictTupleResponse(BaseModel):
    items: tuple[int, ...] = Field(strict=True)


class PathResponse(BaseModel):
    value: int = Field(validation_alias=AliasPath("payload", "value"))


@pytest.mark.parametrize(
    "result",
    [
        StrictTupleResponse(items=(7,)),
        PathResponse.model_construct(value=7),
        RootModel[int](7),
    ],
)
def test_structural_revalidation_preserves_valid_python_output_shapes(
    result: BaseModel,
):
    output = type(result)

    def operation(value: int):
        return result

    summon = Summon("test")

    @summon("/shapes")
    def endpoint(
        request: Request,
        response=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=output),
            calls=Exactly(1),
        ),
    ) -> output:  # type: ignore[valid-type]
        """Preserve valid native fields during revalidation."""
        ...

    assert (
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )
        == result
    )


class NestedResponse(BaseModel):
    items: list[Response]


class CollisionResponse(BaseModel):
    x: int = Field(alias="y")
    y: int


class AnyResponse(BaseModel):
    payload: Any


@pytest.mark.parametrize(
    "result",
    [
        CollisionResponse.model_validate(
            {"x": 1, "y": 2}, by_alias=False, by_name=True
        ),
        AnyResponse(payload=Request(value=7)),
    ],
)
def test_revalidation_preserves_canonical_fields_and_any_payloads(result: BaseModel):
    output = type(result)

    def operation(value: int):
        return result

    summon = Summon("test")

    @summon("/canonical")
    def endpoint(
        request: Request,
        response=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=output),
            calls=Exactly(1),
        ),
    ) -> output:  # type: ignore[valid-type]
        """Preserve the declared field semantics."""
        ...

    assert (
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )
        == result
    )


def test_serializer_cannot_launder_invalid_declared_fields():
    def operation(value: int) -> Response:
        return Response.model_construct(value="invalid")

    summon = Summon("test")

    @summon("/probe")
    def endpoint(
        request: Request,
        result=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=Response),
            calls=Exactly(1),
        ),
    ) -> Response:
        """Return the operation result."""
        ...

    with pytest.raises(_OperationOutputError):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 1})
        )


@pytest.mark.parametrize("invalid", [False, True])
def test_nested_serializer_and_alias_fields_are_structurally_validated(invalid: bool):
    def operation(value: int) -> NestedResponse:
        return NestedResponse.model_construct(
            items=[Response.model_construct(value="invalid" if invalid else value)]
        )

    summon = Summon("test")

    @summon("/nested")
    def endpoint(
        request: Request,
        result=Required(
            Operation(
                operation, bind={"value": FromRequest("value")}, output=NestedResponse
            ),
            calls=Exactly(1),
        ),
    ) -> NestedResponse:
        """Return nested results."""
        ...

    call = Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
    if invalid:
        with pytest.raises(_OperationOutputError):
            asyncio.run(call)
    else:
        assert asyncio.run(call).items[0].value == 7
