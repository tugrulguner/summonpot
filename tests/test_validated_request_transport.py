"""HTTP validation is a single boundary, not a serialization round trip."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    AliasChoices,
    AliasPath,
    BaseModel,
    BeforeValidator,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import (
    _prepare_request,
    _registered_plan,
    _RequestValues,
    _TransportRequest,
    _validated_transport_request,
)
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Result(BaseModel):
    value: int


def service(request_model: type[BaseModel], calls: list[Any]) -> Summon:
    def apply(value: int) -> Result:
        calls.append(value)
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("transport", model="invalid-provider:no-model")

    @summon("/apply")
    def endpoint(
        request: request_model,  # type: ignore[valid-type]  # pyright: ignore[reportInvalidTypeForm]
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply the validated value exactly once."""
        ...

    return summon


@pytest.mark.parametrize(
    ("alias", "payload"),
    [
        ("external", {"external": 3}),
        (AliasPath("nested", "number"), {"nested": {"number": 3}}),
        (AliasChoices("external", AliasPath("nested", "number")), {"external": 3}),
        (
            AliasChoices("external", AliasPath("nested", "number")),
            {"nested": {"number": 3}},
        ),
    ],
)
def test_http_validation_aliases(alias: Any, payload: dict[str, Any]):
    class Request(BaseModel):
        value: int = Field(validation_alias=alias, serialization_alias="display")

    calls: list[Any] = []
    summon = service(Request, calls)
    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/apply", json=payload
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 3}
    assert calls == [3]


def test_http_field_validator_runs_once_before_side_effect():
    validations: list[int] = []

    class Request(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def increment(cls, value: int) -> int:
            validations.append(value)
            return value + 1

    calls: list[Any] = []
    summon = service(Request, calls)
    response = TestClient(build_app(summon)).post("/apply", json={"value": 3})
    assert response.status_code == 200
    assert response.json() == {"value": 4}
    assert validations == [3]
    assert calls == [4]


def test_raw_runtime_alias_mapping_validates_once():
    validations: list[int] = []

    class Request(BaseModel):
        value: int = Field(validation_alias=AliasPath("nested", "value"))

        @field_validator("value")
        @classmethod
        def increment(cls, value: int) -> int:
            validations.append(value)
            return value + 1

    calls: list[Any] = []
    summon = service(Request, calls)
    result = asyncio.run(Runtime().call(summon.endpoints[0], {"nested": {"value": 3}}))
    assert result.value == 4
    assert validations == [3]
    assert calls == [4]


def test_http_model_validator_and_serializer_run_once():
    events: list[str] = []

    class Request(BaseModel):
        value: int

        @model_validator(mode="after")
        def increment(self):
            events.append("validate")
            self.value += 1
            return self

        @field_serializer("value")
        def display(self, value: int) -> str:
            events.append("serialize")
            return f"display:{value}"

    calls: list[Any] = []
    summon = service(Request, calls)
    response = TestClient(build_app(summon)).post("/apply", json={"value": 3})
    assert response.status_code == 200
    assert response.json() == {"value": 4}
    assert events == ["validate", "serialize"]
    assert calls == [4]


def test_http_preserves_strict_native_uuid_after_validation():
    requested = UUID("12345678-1234-5678-1234-567812345678")
    validations: list[Any] = []
    received: list[UUID] = []

    def parse(value: Any) -> UUID:
        validations.append(value)
        return UUID(value)

    class Request(BaseModel):
        value: Annotated[UUID, Field(strict=True), BeforeValidator(parse)]

    def apply(value: UUID) -> Result:
        received.append(value)
        return Result(value=3)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("uuid", model="invalid-provider:no-model")

    @summon("/uuid")
    def endpoint(
        request: Request, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Pass a native UUID without revalidation."""
        ...

    response = TestClient(build_app(summon)).post(
        "/uuid", json={"value": str(requested)}
    )
    assert response.status_code == 200
    assert received == [requested]
    assert type(received[0]) is UUID
    assert validations == [str(requested)]


@pytest.mark.parametrize(
    "method,path",
    [("POST", "/scalar"), ("GET", "/scalar"), ("POST", "/scalar/{value}")],
)
def test_scalar_http_validator_runs_once(method: str, path: str):
    validations: list[int] = []
    calls: list[int] = []

    def increment(value: int) -> int:
        validations.append(value)
        return value + 1

    def apply(value: int) -> Result:
        calls.append(value)
        return Result(value=value)

    turns = 0

    def model(messages, info):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("apply", {})])
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"value": 4})]
        )

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("scalar")
    summon._runtime = Runtime(model=FunctionModel(model))

    @summon(path, method=method)
    def endpoint(
        value: Annotated[int, AfterValidator(increment)],
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Use validated scalar input in the operation."""
        ...

    client = TestClient(build_app(summon))
    if "{value}" in path:
        response = client.post("/scalar/3")
    elif method == "GET":
        response = client.get(path, params={"value": 3})
    else:
        response = client.post(path, json={"value": 3})
    assert response.status_code == 200, response.text
    assert calls == [4]
    assert validations == [3]


@pytest.mark.parametrize("wrapper", [_RequestValues, _TransportRequest])
def test_manually_constructed_carrier_is_not_trusted(wrapper):
    class Request(BaseModel):
        value: int = Field(ge=1)

    calls: list[Any] = []
    summon = service(Request, calls)
    params = wrapper({"value": -1}, typed={"value": 10})
    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(summon.endpoints[0], params))
    assert calls == []


def test_transport_carrier_cannot_cross_plans():
    class Request(BaseModel):
        value: int

    first = service(Request, [])
    calls: list[Any] = []
    second = service(Request, calls)
    plan = _registered_plan(first.endpoints[0])
    assert plan is not None
    carrier = _validated_transport_request(plan, {"value": 3}, typed={"value": 3})
    with pytest.raises(ValueError, match="different endpoint plan"):
        asyncio.run(Runtime().call(second.endpoints[0], carrier))
    assert calls == []


def test_transport_snapshot_detaches_all_mutable_public_views():
    class Request(BaseModel):
        value: list[int]

    summon = service(Request, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    source = {"value": [3]}
    carrier = _validated_transport_request(plan, source, typed=source)
    source["value"].append(4)
    carrier["value"].append(5)
    carrier.typed["value"].append(6)
    carrier.typed = {"value": [999]}
    prepared = _prepare_request(plan, carrier)
    assert prepared.typed["value"] == [3]
    assert prepared["value"] == [3]
    prepared.typed["value"].append(7)
    assert _prepare_request(plan, carrier).typed["value"] == [3]


def test_untrusted_scalar_carrier_uses_external_mapping():
    summon = Summon("scalar")

    @summon("/scalar")
    def endpoint(value: int) -> str:
        """Validate the actual external scalar."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    with pytest.raises(ValidationError):
        _prepare_request(plan, _RequestValues({"value": "invalid"}, typed={"value": 3}))
    assert (
        _prepare_request(
            plan, _RequestValues({"value": "4"}, typed={"value": 99})
        ).typed["value"]
        == 4
    )


def test_http_carrier_mutation_cannot_change_validated_operation_input(monkeypatch):
    class Request(BaseModel):
        value: int

    calls: list[Any] = []
    summon = service(Request, calls)
    original_call = summon._runtime.call

    async def mutate(endpoint, params):
        params["value"] = 999
        params.typed = {"value": 888}
        return await original_call(endpoint, params)

    monkeypatch.setattr(summon._runtime, "call", mutate)
    response = TestClient(build_app(summon)).post("/apply", json={"value": 3})
    assert response.status_code == 200
    assert response.json() == {"value": 3}
    assert calls == [3]


def test_http_cannot_claim_validated_provenance():
    class Request(BaseModel):
        value: int = Field(ge=1)

    calls: list[Any] = []
    summon = service(Request, calls)
    client = TestClient(build_app(summon))
    response = client.post(
        "/apply",
        json={
            "value": -1,
            "typed": {"value": 3},
            "_plan": {},
            "_validated": True,
        },
    )
    assert response.status_code == 422
    assert calls == []


def test_transport_snapshot_lifetime_follows_carrier():
    from summonpot._execution import _TRANSPORT_SNAPSHOTS

    class Request(BaseModel):
        value: int

    summon = service(Request, [])
    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    carrier = _validated_transport_request(plan, {"value": 3}, typed={"value": 3})
    identity = id(carrier)
    assert identity in _TRANSPORT_SNAPSHOTS
    del carrier
    assert identity not in _TRANSPORT_SNAPSHOTS
