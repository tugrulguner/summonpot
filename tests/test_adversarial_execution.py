"""Regression probes for direct-execution trust boundaries."""

import asyncio
import threading
from typing import Annotated, Any, Literal, cast

import pytest
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    Field,
    RootModel,
    field_serializer,
    model_serializer,
)

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


class ChoiceResponse(BaseModel):
    value: int = Field(validation_alias=AliasChoices("external", AliasPath("data", 0)))


class MixedAliases(BaseModel):
    path: PathResponse
    choice: ChoiceResponse
    collision: CollisionResponse


class RecursiveResponse(BaseModel):
    value: int = Field(alias="external")
    children: list["RecursiveResponse"] = Field(default_factory=list)


class CatResponse(BaseModel):
    kind: Literal["cat"]
    value: int = Field(alias="external")


class DogResponse(BaseModel):
    kind: Literal["dog"]
    value: int


class UnionResponse(BaseModel):
    pet: Annotated[CatResponse | DogResponse, Field(discriminator="kind")]


class SerializedResponse(BaseModel):
    value: int
    hidden: int = Field(exclude=True)

    @field_serializer("value")
    def serialize_value(self, value: int) -> str:
        return f"serialized:{value}"


class SerializedRoot(RootModel[int]):
    @model_serializer
    def serialize_root(self) -> str:
        return "not-an-integer"


def _output_endpoint(output: Any, result: Any):
    def operation(value: int):
        return result

    summon = Summon("test")

    @summon("/schema-output")
    def endpoint(
        request: Request,
        response=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=output),
            calls=Exactly(1),
        ),
    ) -> output:  # type: ignore[valid-type]
        """Validate application output without serialization."""
        ...

    return summon.endpoints[0]


@pytest.mark.parametrize("outer_instance", [False, True])
@pytest.mark.parametrize("inner_instance", [False, True])
def test_each_nested_model_selects_its_own_alias_policy(
    outer_instance: bool, inner_instance: bool
):
    fields = {
        "path": PathResponse.model_construct(value=7)
        if inner_instance
        else {"payload": {"value": 7}},
        "choice": ChoiceResponse.model_construct(value=8)
        if inner_instance
        else {"data": [8]},
        "collision": CollisionResponse.model_validate(
            {"x": 1, "y": 2}, by_alias=False, by_name=True
        )
        if inner_instance
        else {"y": 2},
    }
    result = MixedAliases.model_construct(**fields) if outer_instance else fields
    endpoint = _output_endpoint(MixedAliases, result)
    validated = asyncio.run(
        Runtime(model="invalid:no-model").call(endpoint, {"value": 7})
    )
    assert validated.path.value == 7
    assert validated.choice.value == 8
    assert (validated.collision.x, validated.collision.y) == (
        1 if inner_instance else 2,
        2,
    )


@pytest.mark.parametrize(
    "output,result,valid",
    [
        (PathResponse, {"payload": {"value": 7}}, True),
        (PathResponse, {"value": 7}, False),
        (ChoiceResponse, {"external": 7}, True),
        (ChoiceResponse, {"value": 7}, False),
        (SerializedResponse, SerializedResponse(value=7, hidden=9), True),
        (
            SerializedResponse,
            SerializedResponse.model_construct(value=7, hidden="bad"),
            False,
        ),
        (SerializedRoot, SerializedRoot(7), True),
        (SerializedRoot, SerializedRoot.model_construct(root=cast(Any, "bad")), False),
        (
            RootModel[list[Response]],
            RootModel[list[Response]]([Response(externalValue=7)]),
            True,
        ),
        (
            RootModel[list[Response]],
            RootModel[list[Response]].model_construct(
                root=[Response.model_construct(value="bad")]
            ),
            False,
        ),
        (
            UnionResponse,
            UnionResponse.model_construct(
                pet=CatResponse.model_construct(kind="cat", value=7)
            ),
            True,
        ),
        (UnionResponse, {"pet": {"kind": "cat", "external": 7}}, True),
        (
            UnionResponse,
            UnionResponse.model_construct(
                pet=CatResponse.model_construct(kind="cat", value="bad")
            ),
            False,
        ),
        (UnionResponse, {"pet": {"kind": "unknown", "value": 7}}, False),
        (
            RecursiveResponse,
            RecursiveResponse.model_construct(
                value=1, children=[RecursiveResponse.model_construct(value=2)]
            ),
            True,
        ),
        (
            RecursiveResponse,
            RecursiveResponse.model_construct(value=1, children=[{"external": 2}]),
            True,
        ),
        (
            RecursiveResponse,
            RecursiveResponse.model_construct(
                value=1, children=[RecursiveResponse.model_construct(value="bad")]
            ),
            False,
        ),
    ],
)
def test_schema_output_regression_matrix(output: Any, result: Any, valid: bool):
    endpoint = _output_endpoint(output, result)
    call = Runtime(model="invalid:no-model").call(endpoint, {"value": 7})
    if not valid:
        with pytest.raises(_OperationOutputError):
            asyncio.run(call)
    else:
        validated = asyncio.run(call)
        assert isinstance(validated, output)
        if isinstance(result, BaseModel) and not (
            isinstance(result, RecursiveResponse)
            and isinstance(result.children[0], dict)
        ):
            assert validated == result


def test_output_validator_is_cached_and_does_not_modify_model_schema(monkeypatch):
    from copy import deepcopy

    from pydantic_core import SchemaValidator

    import summonpot._execution as execution

    schema = deepcopy(Response.__pydantic_core_schema__)
    result = Response.model_construct(value="invalid")
    endpoint = _output_endpoint(Response, result)
    plan = _registered_plan(endpoint)
    assert plan is not None
    validator = plan.tools[0].output_validator
    assert isinstance(validator, SchemaValidator)
    assert Response.__pydantic_core_schema__ == schema
    assert Response.model_validate(result) is result

    def forbid_compile(*args, **kwargs):
        pytest.fail("Output validator was compiled during a request")

    monkeypatch.setattr(execution, "_compile_output_validator", forbid_compile)
    for _ in range(2):
        with pytest.raises(_OperationOutputError):
            asyncio.run(Runtime(model="invalid:no-model").call(endpoint, {"value": 7}))
    assert plan.tools[0].output_validator is validator


def test_invalid_output_consumes_reservation_without_success_or_fallback(monkeypatch):
    from pydantic_ai import ModelRetry

    import summonpot.runtime as runtime_module
    from summonpot._execution import _new_run
    from summonpot.runtime import _invoke_bound_operation

    endpoint = _output_endpoint(
        Response, Response.model_construct(value="secret-invalid")
    )
    plan = _registered_plan(endpoint)
    assert plan is not None
    captured = []
    original_new_run = runtime_module._new_run

    def capture_run(*args, **kwargs):
        run = original_new_run(*args, **kwargs)
        captured.append(run)
        return run

    monkeypatch.setattr(runtime_module, "_new_run", capture_run)
    with pytest.raises(_OperationOutputError, match="invalid declared output") as error:
        asyncio.run(Runtime(model="invalid:no-model").call(endpoint, {"value": 7}))
    assert "secret-invalid" not in str(error.value)
    state = captured[0].states[0]
    assert (state.started, state.running, state.succeeded) == (1, 0, 0)

    async def attempt_twice():
        run = _new_run(plan, {"value": 7})
        with pytest.raises(_OperationOutputError):
            await _invoke_bound_operation(plan.tools[0], run, {})
        with pytest.raises(ModelRetry, match="already started"):
            await _invoke_bound_operation(plan.tools[0], run, {})
        assert (run.states[0].started, run.states[0].succeeded) == (1, 0)

    asyncio.run(attempt_twice())


@pytest.mark.parametrize("pydantic_dataclass", [False, True])
@pytest.mark.parametrize("invalid", [False, True])
def test_nested_dataclass_instances_are_revalidated(
    pydantic_dataclass: bool, invalid: bool
):
    from dataclasses import dataclass

    from pydantic.dataclasses import dataclass as validated_dataclass

    decorate = validated_dataclass if pydantic_dataclass else dataclass

    @decorate
    class Item:
        value: int

    class Envelope(BaseModel):
        item: Item

    item = cast(Any, Item)(7)
    if invalid:
        object.__setattr__(item, "value", "bad")
    endpoint = _output_endpoint(Envelope, Envelope.model_construct(item=item))
    call = Runtime(model="invalid:no-model").call(endpoint, {"value": 7})
    if invalid:
        with pytest.raises(_OperationOutputError):
            asyncio.run(call)
    else:
        assert asyncio.run(call).item.value == 7


@pytest.mark.parametrize("instance", [False, True])
def test_dataclass_alias_policy_is_local(instance: bool):
    from pydantic.dataclasses import dataclass

    @dataclass
    class Item:
        value: int = Field(validation_alias=AliasPath("payload", "value"))

    class Envelope(BaseModel):
        item: Item

    item = object.__new__(Item)
    object.__setattr__(item, "value", 7)
    result = Envelope.model_construct(
        item=item if instance else {"payload": {"value": 7}}
    )
    endpoint = _output_endpoint(Envelope, result)
    assert (
        asyncio.run(
            Runtime(model="invalid:no-model").call(endpoint, {"value": 7})
        ).item.value
        == 7
    )


def test_labeled_union_schemas_are_revalidated_and_default_data_is_untouched():
    from pydantic import TypeAdapter, ValidationError
    from pydantic_core import SchemaValidator, core_schema

    from summonpot._output_validation import _revalidating_schema

    schema = core_schema.union_schema(
        [
            (TypeAdapter(Response).core_schema, "response"),
            (core_schema.int_schema(), "integer"),
        ]
    )
    validator = SchemaValidator(_revalidating_schema(schema), _use_prebuilt=False)
    with pytest.raises(ValidationError):
        validator.validate_python(Response.model_construct(value="bad"))
    assert validator.validate_python(Response.model_construct(value=7)).value == 7
    default = {"type": "model", "cls": Response, "schema": {"type": "any"}}
    copied = _revalidating_schema(
        core_schema.with_default_schema(core_schema.any_schema(), default=default)
    )
    assert copied["default"] is default


def test_schema_named_fields_do_not_bypass_nested_revalidation():
    class Envelope(BaseModel):
        default: Response
        metadata: Response
        type: Response

    invalid = Response.model_construct(value="bad")
    endpoint = _output_endpoint(
        Envelope,
        Envelope.model_construct(default=invalid, metadata=invalid, type=invalid),
    )
    with pytest.raises(_OperationOutputError):
        asyncio.run(Runtime(model="invalid:no-model").call(endpoint, {"value": 7}))
