"""Raw Runtime.call inputs match generated HTTP request semantics."""

from __future__ import annotations

import asyncio
from collections import UserDict
from collections.abc import Mapping
from dataclasses import dataclass, field, make_dataclass
from enum import Enum
from typing import Annotated, Any, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
    RootModel,
    ValidationError,
    create_model,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from typing_extensions import TypeAliasType, TypedDict

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Result(BaseModel):
    value: int


RecursiveJson = TypeAliasType(
    "RecursiveJson",
    "dict[str, RecursiveJson] | list[RecursiveJson] | str | int | None",
)


def _scalar_service(
    annotation: Any,
    received: list[Any],
    *,
    default: Any = ...,
) -> Summon:
    def apply(value: Any) -> Result:
        received.append(value)
        return Result(value=len(value) if isinstance(value, list) else value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    turns = 0

    def model(messages, info):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("apply", {})])
        value = received[-1]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"value": len(value) if isinstance(value, list) else value},
                )
            ]
        )

    summon = Summon("scalar-parity")
    summon._runtime = Runtime(model=FunctionModel(model))

    namespace = {
        "__name__": __name__,
        "annotation": annotation,
        "default": default,
        "operation": operation,
        "Result": Result,
        "summon": summon,
    }
    if default is ...:
        exec(
            compile(
                """
@summon("/value")
def endpoint(value: annotation, result=Required(operation, calls=Exactly(1))) -> Result:
    \"\"\"Apply one scalar value.\"\"\"
    ...
""",
                "<scalar-required>",
                "exec",
                dont_inherit=True,
            ),
            {**globals(), **namespace},
        )
    else:
        exec(
            compile(
                """
@summon("/value")
def endpoint(value: annotation = default, result=Required(operation, calls=Exactly(1))) -> Result:
    \"\"\"Apply one scalar value.\"\"\"
    ...
""",
                "<scalar-default>",
                "exec",
                dont_inherit=True,
            ),
            {**globals(), **namespace},
        )
    return summon


def test_raw_scalar_missing_required_field_matches_http_rejection():
    raw = _scalar_service(int, [])
    http = _scalar_service(int, [])

    with pytest.raises(ValidationError):
        asyncio.run(raw._runtime.call(raw.endpoints[0], {}))

    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/value", json={}
    )
    assert response.status_code == 422


def test_raw_scalar_default_matches_http_and_is_canonical():
    raw_received: list[Any] = []
    http_received: list[Any] = []
    raw = _scalar_service(int, raw_received, default=7)
    http = _scalar_service(int, http_received, default=7)

    result = asyncio.run(raw._runtime.call(raw.endpoints[0], {}))
    response = TestClient(build_app(http)).post("/value", json={})

    assert result == Result(value=7)
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 7}
    assert raw_received == [7]
    assert http_received == [7]
    assert type(raw_received[0]) is type(http_received[0]) is int


def test_raw_scalar_alias_matches_http_and_produces_canonical_type():
    annotation = Annotated[int, Field(alias="external")]
    raw_received: list[Any] = []
    http_received: list[Any] = []
    raw = _scalar_service(annotation, raw_received)
    http = _scalar_service(annotation, http_received)

    result = asyncio.run(raw._runtime.call(raw.endpoints[0], {"external": "8"}))
    response = TestClient(build_app(http)).post("/value", json={"external": "8"})

    assert result == Result(value=8)
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 8}
    assert raw_received == [8]
    assert http_received == [8]
    assert type(raw_received[0]) is type(http_received[0]) is int


def test_raw_scalar_alias_rejects_field_name_when_http_rejects_it():
    annotation = Annotated[int, Field(alias="external")]
    raw = _scalar_service(annotation, [])
    http = _scalar_service(annotation, [])

    with pytest.raises(ValidationError):
        asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": 8}))

    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/value", json={"value": 8}
    )
    assert response.status_code == 422


def test_scalar_validator_runs_once_at_each_public_boundary():
    validations: list[int] = []

    def increment(value: int) -> int:
        validations.append(value)
        return value + 1

    annotation = Annotated[int, AfterValidator(increment)]
    raw_received: list[Any] = []
    raw = _scalar_service(annotation, raw_received)

    result = asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": 3}))

    assert result == Result(value=4)
    assert raw_received == [4]
    assert validations == [3]

    http_received: list[Any] = []
    http = _scalar_service(annotation, http_received)
    response = TestClient(build_app(http)).post("/value", json={"value": 5})

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 6}
    assert http_received == [6]
    assert validations == [3, 5]


def _model_service(request_model: type[BaseModel], received: list[Any]) -> Summon:
    def apply(value: Any) -> Result:
        received.append(value)
        return Result(value=len(value) if isinstance(value, list) else int(value))

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("model-parity")

    def endpoint(request: Any, result=Required(operation, calls=Exactly(1))) -> Result:
        """Apply one model field."""
        ...

    endpoint.__annotations__["request"] = request_model
    summon("/model")(endpoint)

    return summon


def test_raw_runtime_rejects_non_exact_outer_mappings_without_hooks():
    hooks: list[str] = []

    class Request(BaseModel):
        value: int

    class HostileMapping(Mapping[str, Any]):
        def __getitem__(self, key: str) -> Any:
            hooks.append("mapping getitem")
            raise RuntimeError("application getitem")

        def __iter__(self):
            hooks.append("mapping iter")
            raise RuntimeError("application iter")

        def __len__(self) -> int:
            hooks.append("mapping len")
            raise RuntimeError("application len")

        def __repr__(self) -> str:
            hooks.append("mapping repr")
            raise RuntimeError("application repr")

    class HostileUserDict(UserDict[str, Any]):
        def __init__(self) -> None:
            self.data = {"value": 7}

        def __getitem__(self, key: str) -> Any:
            hooks.append("userdict getitem")
            raise RuntimeError("application getitem")

        def __iter__(self):
            hooks.append("userdict iter")
            raise RuntimeError("application iter")

        def __repr__(self) -> str:
            hooks.append("userdict repr")
            raise RuntimeError("application repr")

    received: list[Any] = []
    summon = _model_service(Request, received)

    assert asyncio.run(Runtime().call(summon.endpoints[0], {"value": 3})) == Result(
        value=3
    )
    for params in (HostileMapping(), HostileUserDict()):
        with pytest.raises(ValidationError, match="exact dictionary"):
            asyncio.run(Runtime().call(summon.endpoints[0], params))

    response = TestClient(build_app(summon)).post("/model", json={"value": 5})
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 5}
    assert received == [3, 5]
    assert hooks == []


def test_model_alias_default_required_and_canonical_values_match_http():
    class Request(BaseModel):
        value: int = Field(alias="external")
        unused_default: int = 11

    raw_received: list[Any] = []
    http_received: list[Any] = []
    raw = _model_service(Request, raw_received)
    http = _model_service(Request, http_received)

    raw_result = asyncio.run(Runtime().call(raw.endpoints[0], {"external": "8"}))
    response = TestClient(build_app(http)).post("/model", json={"external": "8"})

    assert raw_result == Result(value=8)
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 8}
    assert raw_received == [8]
    assert http_received == [8]
    assert type(raw_received[0]) is type(http_received[0]) is int

    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(raw.endpoints[0], {}))
    rejected = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/model", json={}
    )
    assert rejected.status_code == 422


def test_model_field_validator_runs_once_for_raw_and_once_for_http():
    validations: list[int] = []

    class Request(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def increment(cls, value: int) -> int:
            validations.append(value)
            return value + 1

    raw_received: list[Any] = []
    raw = _model_service(Request, raw_received)
    raw_result = asyncio.run(Runtime().call(raw.endpoints[0], {"value": 3}))

    assert raw_result == Result(value=4)
    assert raw_received == [4]
    assert validations == [3]

    http_received: list[Any] = []
    http = _model_service(Request, http_received)
    response = TestClient(build_app(http)).post("/model", json={"value": 5})

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 6}
    assert http_received == [6]
    assert validations == [3, 5]


def test_custom_init_request_runs_once_for_direct_raw_and_http():
    initializations: list[int] = []
    validations: list[int] = []

    class Request(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def increment(cls, value: int) -> int:
            validations.append(value)
            return value + 1

        def __init__(self, *, value: int) -> None:
            initializations.append(value)
            super().__init__(value=value + 1)

    raw_received: list[Any] = []
    raw = _model_service(Request, raw_received)
    raw_result = asyncio.run(Runtime().call(raw.endpoints[0], {"value": 3}))

    assert raw_result == Result(value=5)
    assert raw_received == [5]
    assert initializations == [3]
    assert validations == [4]

    http_received: list[Any] = []
    http = _model_service(Request, http_received)
    response = TestClient(build_app(http)).post("/model", json={"value": 5})

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 7}
    assert http_received == [7]
    assert initializations == [3, 5]
    assert validations == [4, 6]


def test_custom_init_hostile_top_level_storage_fails_closed_for_raw_only():
    hooks: list[str] = []
    base_descriptor = BaseModel.__dict__["__dict__"]

    class HostileDict(dict[str, Any]):
        def __contains__(self, key: object) -> bool:
            hooks.append("contains")
            raise RuntimeError("application contains")

        def __getitem__(self, key: str) -> Any:
            hooks.append("getitem")
            raise RuntimeError("application getitem")

        def __iter__(self):
            hooks.append("iter")
            raise RuntimeError("application iter")

        def items(self):
            hooks.append("items")
            raise RuntimeError("application items")

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class Request(BaseModel):
        value: int

        def __init__(self, *, value: int) -> None:
            super().__init__(value=value)
            base_descriptor.__set__(self, HostileDict(value=value))

    raw_received: list[Any] = []
    raw = _model_service(Request, raw_received)
    with pytest.raises(ValidationError, match="canonical storage"):
        asyncio.run(Runtime().call(raw.endpoints[0], {"value": 7}))

    http_received: list[Any] = []
    http = _model_service(Request, http_received)
    response = TestClient(build_app(http)).post("/model", json={"value": 11})

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 11}
    assert raw_received == []
    assert http_received == [11]
    assert hooks == []


def test_custom_init_exact_storage_with_hostile_key_fails_before_equality():
    hooks: list[str] = []
    armed = [False]
    base_descriptor = BaseModel.__dict__["__dict__"]

    class HostileKey:
        def __hash__(self) -> int:
            return hash("value")

        def __eq__(self, other: object) -> bool:
            if armed[0]:
                hooks.append("eq")
                raise AssertionError("application equality ran")
            return False

        def __repr__(self) -> str:
            hooks.append("repr")
            raise AssertionError("application repr ran")

    class Request(BaseModel):
        value: int

        def __init__(self, *, value: int) -> None:
            super().__init__(value=value)
            storage: dict[object, Any] = {HostileKey(): "hidden", "value": value}
            base_descriptor.__set__(self, storage)
            armed[0] = True

    raw_received: list[Any] = []
    raw = _model_service(Request, raw_received)
    with pytest.raises(ValidationError, match="canonical storage"):
        asyncio.run(Runtime().call(raw.endpoints[0], {"value": 7}))

    armed[0] = False
    http_received: list[Any] = []
    http = _model_service(Request, http_received)
    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/model", json={"value": 11}
    )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert raw_received == []
    assert http_received == []
    assert hooks == []


def test_custom_init_request_runs_once_for_agent_raw_and_http():
    initializations: list[int] = []
    received: list[int] = []

    class Request(BaseModel):
        value: int

        def __init__(self, *, value: int) -> None:
            initializations.append(value)
            super().__init__(value=value + 1)

    class AgentResult(BaseModel):
        answer: int

    def apply(value: int) -> Result:
        received.append(value)
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)

    def service(name: str) -> Summon:
        turns = 0

        def model(messages, info):
            nonlocal turns
            turns += 1
            if turns == 1:
                return ModelResponse(parts=[ToolCallPart("apply", {})])
            return ModelResponse(
                parts=[
                    ToolCallPart(info.output_tools[0].name, {"answer": received[-1]})
                ]
            )

        summon = Summon(name)

        def endpoint(
            request: Any,
            result=Required(operation, calls=Exactly(1)),
        ) -> AgentResult:
            """Apply one value through the agent path."""
            ...

        endpoint.__annotations__["request"] = Request
        endpoint.__annotations__["return"] = AgentResult
        summon("/model")(endpoint)
        summon._runtime = Runtime(model=FunctionModel(model))
        return summon

    raw = service("custom-init-agent-raw")
    raw_result = asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": 7}))

    http = service("custom-init-agent-http")
    response = TestClient(build_app(http)).post("/model", json={"value": 9})

    assert raw_result == AgentResult(answer=8)
    assert response.status_code == 200, response.text
    assert response.json() == {"answer": 10}
    assert received == [8, 10]
    assert initializations == [7, 9]


@pytest.mark.parametrize("agent_backed", [False, True])
def test_custom_init_structural_pass_preserves_canonical_request_and_field_identity(
    agent_backed: bool,
):
    events: list[str] = []
    canonical_values: list[HookedList] = []
    canonical_requests: list[Request] = []
    received: list[HookedList] = []

    class HookedList(list[int]):
        def __copy__(self):
            events.append("copy")
            return [999]

        def __deepcopy__(self, memo=None):
            events.append("deepcopy")
            return [999]

        def __str__(self) -> str:
            events.append("str")
            return "lossy"

        def __repr__(self) -> str:
            events.append("repr")
            return "lossy"

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            return False

        def __hash__(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
            events.append("hash")
            return 0

    def make_canonical(value: list[int]) -> HookedList:
        canonical = HookedList(value)
        canonical_values.append(canonical)
        return canonical

    class Request(BaseModel):
        value: Annotated[list[int], AfterValidator(make_canonical)]

        @field_serializer("value")
        def serialize_value(self, value: list[int]) -> str:
            events.append("serialize")
            return "lossy"

        def __init__(self, *, value: list[int]) -> None:
            super().__init__(value=value)
            canonical_requests.append(self)

    class AgentResult(BaseModel):
        answer: int

    def apply(value: HookedList) -> Result:
        received.append(value)
        return Result(value=len(value))

    apply.__annotations__ = {"value": list[int], "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    turns = 0

    def model(messages, info):
        nonlocal turns
        turns += 1
        if turns == 1:
            return ModelResponse(parts=[ToolCallPart("apply", {})])
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"answer": 1})]
        )

    summon = Summon(f"canonical-identity-{'agent' if agent_backed else 'direct'}")
    runtime = Runtime(model=FunctionModel(model)) if agent_backed else Runtime()
    summon._runtime = runtime

    def endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Any:
        """Apply the canonical request field without reconstructing it."""
        ...

    endpoint.__annotations__["request"] = Request
    endpoint.__annotations__["return"] = AgentResult if agent_backed else Result
    summon("/identity")(endpoint)

    plan = runtime._plan_for(summon.endpoints[0])
    admitted = plan.input_validator.validate_python({"value": [1]})

    assert admitted is canonical_requests[0]
    assert admitted.value is canonical_values[0]
    assert events == []

    result = asyncio.run(runtime.call(summon.endpoints[0], {"value": [2]}))

    if isinstance(result, Result):
        assert result.value == 1
    else:
        assert result.answer == 1
    assert len(received) == 1
    assert received[0] is canonical_values[1]
    assert type(received[0]) is HookedList
    assert len(canonical_requests) == 2
    assert events == []


def test_custom_init_request_still_rejects_invalid_nested_constructed_model():
    initializations: list[Inner] = []
    operation_calls: list[Inner] = []
    hooks: list[str] = []

    class Inner(BaseModel):
        x: int

        @field_validator("x")
        @classmethod
        def require_positive(cls, value: int) -> int:
            if value <= 0:
                raise ValueError("must be positive")
            return value

        @field_serializer("x")
        def serialize_x(self, value: int) -> int:
            hooks.append("serialize")
            return value

        def __copy__(self):
            hooks.append("copy")
            return self

        def __deepcopy__(self, memo=None):
            hooks.append("deepcopy")
            return self

        def __repr__(self) -> str:
            hooks.append("repr")
            return "inner"

        def __eq__(self, other: object) -> bool:
            hooks.append("eq")
            return False

        def __hash__(self) -> int:
            hooks.append("hash")
            return 0

    class Request(BaseModel):
        value: Inner

        def __init__(self, *, value: Inner) -> None:
            initializations.append(value)
            super().__init__(value=value)

    def apply(value: Inner) -> Result:
        operation_calls.append(value)
        return Result(value=value.x)

    apply.__annotations__ = {"value": Any, "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("custom-init-structural-admission")

    def endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one structurally valid nested value."""
        ...

    endpoint.__annotations__["request"] = Request
    summon("/model")(endpoint)

    invalid = Inner.model_construct(x=-1)
    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(summon.endpoints[0], {"value": invalid}))

    assert initializations == []
    assert operation_calls == []
    assert hooks == []


def test_custom_init_rejects_coercing_nested_constructed_model():
    initializations: list[Inner] = []
    received: list[Any] = []

    class Inner(BaseModel):
        x: int

    class Request(BaseModel):
        value: Inner

        def __init__(self, *, value: Inner) -> None:
            initializations.append(value)
            super().__init__(value=value)

    summon = _model_service(Request, received)

    with pytest.raises(ValidationError, match="equivalent mapping"):
        asyncio.run(
            Runtime().call(summon.endpoints[0], {"value": Inner.model_construct(x="7")})
        )

    assert initializations == []
    assert received == []


@pytest.mark.parametrize("constructed_x", [-1, "7"])
def test_custom_init_rejects_constructed_model_dict_keys_without_hooks(
    constructed_x: Any,
):
    events: list[str] = []
    initializations: list[dict[Any, int]] = []
    received: list[dict[Any, int]] = []

    class Inner(BaseModel):
        model_config = {"frozen": True}

        x: int = Field(gt=0)

        @field_serializer("x")
        def serialize_x(self, value: int) -> int:
            events.append("serialize")
            return value

        def __getattribute__(self, name: str) -> Any:
            if name == "x":
                events.append("attribute")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            events.append("repr")
            return "inner"

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            return self is other

        def __hash__(self) -> int:
            events.append("hash")
            return 1

    class Request(BaseModel):
        payload: Any

        def __init__(self, *, payload: Any) -> None:
            initializations.append(payload)
            super().__init__(payload=payload)

    def apply(payload: dict[Any, int]) -> Result:
        received.append(payload)
        return Result(value=len(payload))

    operation = Operation(
        apply, bind={"payload": FromRequest("payload")}, output=Result
    )
    summon = Summon("custom-init-dict-key-admission")

    def endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one dictionary after request admission."""
        ...

    endpoint.__annotations__["request"] = Request
    summon("/dict-key")(endpoint)

    key = Inner.model_construct(x=constructed_x)
    payload = {key: 1}
    events.clear()  # Building the dictionary necessarily hashes its key once.

    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(summon.endpoints[0], {"payload": payload}))

    assert initializations == []
    assert received == []
    assert events == []


def test_custom_init_rejects_raw_container_graph_beyond_scan_limit():
    initializations: list[Any] = []
    operation_calls: list[Any] = []
    summon = _custom_init_payload_service(
        "custom-init-deep-admission", initializations, operation_calls
    )
    payload: Any = "leaf"
    for _ in range(64):
        payload = [payload]

    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(summon.endpoints[0], {"payload": payload}))

    assert initializations == []
    assert operation_calls == []


@pytest.mark.parametrize(
    "container_kind",
    ["list-subclass", "dict-subclass", "user-dict", "iterator"],
)
def test_custom_init_rejects_uninspectable_container_like_values_without_hooks(
    container_kind: str,
):
    events: list[str] = []
    initializations: list[Any] = []
    received: list[Any] = []

    class Inner(BaseModel):
        x: int = Field(gt=0)

        @field_serializer("x")
        def serialize_x(self, value: int) -> int:
            events.append("serializer")
            raise RuntimeError("application serializer")

        def __repr__(self) -> str:
            events.append("repr")
            raise RuntimeError("application repr")

    class HostileList(list[Any]):
        def __iter__(self):
            events.append("iter")
            raise RuntimeError("application iteration")

        def __getitem__(self, key):
            events.append("getitem")
            raise RuntimeError("application indexing")

    class HostileDict(dict[str, Any]):
        def __iter__(self):
            events.append("iter")
            raise RuntimeError("application iteration")

        def items(self):
            events.append("items")
            raise RuntimeError("application items")

    class HostileUserDict(UserDict[str, Any]):
        def __iter__(self):
            events.append("iter")
            raise RuntimeError("application iteration")

        def __getitem__(self, key):
            events.append("getitem")
            raise RuntimeError("application indexing")

    class HostileIterator:
        def __init__(self, item: Any) -> None:
            self.item = item

        def __iter__(self):
            events.append("iter")
            raise RuntimeError("application iteration")

        def __next__(self):
            events.append("next")
            raise RuntimeError("application next")

    invalid = Inner.model_construct(x="7")
    payloads = {
        "list-subclass": HostileList([invalid]),
        "dict-subclass": HostileDict(value=invalid),
        "user-dict": HostileUserDict(value=invalid),
        "iterator": HostileIterator(invalid),
    }
    summon = _custom_init_payload_service(
        f"custom-init-{container_kind}", initializations, received
    )

    with pytest.raises(ValidationError, match="equivalent mapping"):
        asyncio.run(
            Runtime().call(summon.endpoints[0], {"payload": payloads[container_kind]})
        )

    assert initializations == []
    assert received == []
    assert events == []


@pytest.mark.parametrize("dataclass_kind", ["normal", "frozen", "slots"])
@pytest.mark.parametrize("constructed_x", [-1, "7"])
def test_custom_init_rejects_dataclass_carriers_before_application_code(
    dataclass_kind: str,
    constructed_x: Any,
):
    events: list[str] = []
    initializations: list[Any] = []
    received: list[Any] = []

    class Inner(BaseModel):
        x: int = Field(gt=0)

        def __getattribute__(self, name: str) -> Any:
            if name == "x":
                events.append("attribute")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            events.append("repr")
            raise RuntimeError("application repr")

    Box = make_dataclass(
        "Box",
        [("inner", Inner)],
        frozen=dataclass_kind == "frozen",
        slots=dataclass_kind == "slots",
    )

    class CustomRequest(BaseModel):
        def __init__(self, **data: Any) -> None:
            initializations.append(data["payload"])
            super().__init__(**data)

    Request = create_model(
        f"DataclassCarrierRequest{dataclass_kind}",
        payload=(Box, ...),
        __base__=CustomRequest,
    )

    def apply(payload: Any) -> Result:
        received.append(payload)
        return Result(value=payload.inner.x)

    apply.__annotations__ = {"payload": InstanceOf[Box], "return": Result}
    operation = Operation(
        apply, bind={"payload": FromRequest("payload")}, output=Result
    )
    summon = Summon(f"custom-init-dataclass-{dataclass_kind}")

    def endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one dataclass-backed request value."""
        ...

    endpoint.__annotations__["request"] = Request
    summon("/dataclass")(endpoint)

    carrier = Box(Inner.model_construct(x=constructed_x))
    with pytest.raises(ValidationError, match="equivalent mapping"):
        asyncio.run(Runtime().call(summon.endpoints[0], {"payload": carrier}))

    assert initializations == []
    assert received == []
    assert events == []


@pytest.mark.parametrize("dataclass_options", [{}, {"frozen": True}, {"slots": True}])
def test_custom_init_dataclass_mapping_matches_http_canonicalization_once(
    dataclass_options: dict[str, bool],
):
    initializations: list[Any] = []
    canonical: list[Any] = []
    received: list[Any] = []

    class Inner(BaseModel):
        x: int = Field(gt=0)

    @dataclass(**dataclass_options)
    class Box:
        inner: Inner

    class Request(BaseModel):
        payload: Box

        def __init__(self, *, payload: Box) -> None:
            initializations.append(payload)
            super().__init__(payload=payload)

        @field_validator("payload", mode="after")
        @classmethod
        def capture_canonical(cls, payload: Box) -> Box:
            canonical.append(payload)
            return payload

    def apply(payload: Any) -> Result:
        received.append(payload)
        return Result(value=payload.inner.x)

    apply.__annotations__ = {"payload": InstanceOf[Box], "return": Result}
    operation = Operation(
        apply, bind={"payload": FromRequest("payload")}, output=Result
    )

    def service(name: str) -> Summon:
        summon = Summon(name)

        def endpoint(
            request: Any,
            result=Required(operation, calls=Exactly(1)),
        ) -> Result:
            """Apply one validated dataclass-backed request value."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/dataclass")(endpoint)
        return summon

    body = {"payload": {"inner": {"x": "7"}}}
    raw = service("custom-init-dataclass-mapping-raw")
    assert asyncio.run(Runtime().call(raw.endpoints[0], body)) == Result(value=7)

    http = service("custom-init-dataclass-mapping-http")
    response = TestClient(build_app(http)).post("/dataclass", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 7}
    assert len(initializations) == len(canonical) == len(received) == 2
    assert all(type(box) is Box for box in received)
    assert all(
        box is expected for box, expected in zip(received, canonical, strict=True)
    )
    assert all(type(box.inner.x) is int for box in received)


def _custom_init_payload_service(
    name: str, initializations: list[Any], received: list[Any]
) -> Summon:
    class Request(BaseModel):
        payload: Any

        def __init__(self, *, payload: Any) -> None:
            initializations.append(payload)
            super().__init__(payload=payload)

    def apply(payload: Any) -> Result:
        received.append(payload)
        return Result(value=1)

    operation = Operation(
        apply, bind={"payload": FromRequest("payload")}, output=Result
    )
    summon = Summon(name)

    def endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one nested request value."""
        ...

    endpoint.__annotations__["request"] = Request
    summon("/payload")(endpoint)
    return summon


def test_custom_init_accepts_depth_64_for_raw_and_http_once():
    initializations: list[Any] = []
    received: list[Any] = []
    raw = _custom_init_payload_service("depth-boundary-raw", initializations, received)
    http = _custom_init_payload_service(
        "depth-boundary-http", initializations, received
    )
    payload: Any = "leaf"
    # The runtime's outer parameter dictionary plus these 63 lists is the
    # maximum 64-container path inspected by request admission.
    for _ in range(63):
        payload = [payload]

    assert asyncio.run(
        Runtime().call(raw.endpoints[0], {"payload": payload})
    ) == Result(value=1)
    assert received[0] is payload
    assert initializations[0] is payload

    response = TestClient(build_app(http)).post("/payload", json={"payload": payload})
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 1}
    assert len(initializations) == len(received) == 2


def test_custom_init_accepts_ordinary_dict_for_raw_and_http_once():
    initializations: list[Any] = []
    received: list[Any] = []
    raw = _custom_init_payload_service("ordinary-dict-raw", initializations, received)
    http = _custom_init_payload_service("ordinary-dict-http", initializations, received)
    payload = {"ordinary": [1, 2]}

    assert asyncio.run(
        Runtime().call(raw.endpoints[0], {"payload": payload})
    ) == Result(value=1)
    assert initializations[0] is received[0] is payload

    response = TestClient(build_app(http)).post("/payload", json={"payload": payload})
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 1}
    assert len(initializations) == len(received) == 2


@pytest.mark.parametrize("shared", [False, True], ids=["cycle", "shared"])
def test_custom_init_accepts_cyclic_and_shared_builtin_graphs_without_recursing(
    shared: bool,
):
    initializations: list[Any] = []
    received: list[Any] = []
    summon = _custom_init_payload_service(
        f"builtin-graph-{shared}", initializations, received
    )
    child: list[Any] = []
    payload = [child, child] if shared else child
    if not shared:
        child.append(child)

    assert asyncio.run(
        Runtime().call(summon.endpoints[0], {"payload": payload})
    ) == Result(value=1)
    assert initializations == [payload]
    assert received == [payload]
    assert initializations[0] is received[0] is payload


def test_custom_init_model_post_init_runs_once_per_raw_and_http_request():
    post_init_calls: list[int] = []

    class Request(BaseModel):
        value: int

        def __init__(self, *, value: int) -> None:
            super().__init__(value=value)

        def model_post_init(self, context: Any) -> None:
            post_init_calls.append(self.value)

    raw = _model_service(Request, [])
    assert asyncio.run(Runtime().call(raw.endpoints[0], {"value": 3})) == Result(
        value=3
    )
    assert post_init_calls == [3]

    http = _model_service(Request, [])
    response = TestClient(build_app(http)).post("/model", json={"value": 5})
    assert response.status_code == 200, response.text
    assert response.json() == {"value": 5}
    assert post_init_calls == [3, 5]


def test_recursive_custom_init_request_with_model_validator_registers():
    class Node(BaseModel):
        child: Node | None = None

        def __init__(self, *, child: Node | None = None) -> None:
            super().__init__(child=child)

        @model_validator(mode="after")
        def preserve_identity(self) -> Node:
            return self

    summon = Summon("recursive-custom-init")

    def endpoint(request: Any) -> str:
        """Accept a recursive request tree."""
        ...

    endpoint.__annotations__["request"] = Node
    summon("/recursive")(endpoint)

    plan = Runtime()._plan_for(summon.endpoints[0])
    validated = plan.input_validator.validate_python({"child": {"child": None}})
    assert isinstance(validated, Node)
    assert isinstance(validated.child, Node)
    assert validated.child.child is None


def test_raw_model_validation_preserves_canonical_value_without_lossy_hooks():
    events: list[str] = []

    class HookedList(list[int]):
        def __deepcopy__(self, memo):
            events.append("copy")
            return [999]

        def __str__(self) -> str:
            events.append("str")
            return "lossy"

        def __repr__(self) -> str:
            events.append("repr")
            return "lossy"

    canonical: list[HookedList] = []

    def make_canonical(value: list[int]) -> HookedList:
        result = HookedList(value)
        canonical.append(result)
        return result

    class Request(BaseModel):
        value: Annotated[list[int], AfterValidator(make_canonical)]

        @field_serializer("value")
        def serialize_value(self, value: list[int]) -> str:
            events.append("serialize")
            return "lossy"

    received: list[Any] = []
    summon = _model_service(Request, received)
    result = asyncio.run(Runtime().call(summon.endpoints[0], {"value": [3]}))

    assert result == Result(value=1)
    assert received == [[3]]
    assert received[0] is canonical[0]
    assert events == []


def test_raw_scalar_validation_preserves_canonical_value_without_value_hooks():
    events: list[str] = []

    class HookedList(list[int]):
        def __deepcopy__(self, memo):
            events.append("copy")
            return [999]

        def __str__(self) -> str:
            events.append("str")
            return "lossy"

        def __repr__(self) -> str:
            events.append("repr")
            return "lossy"

    canonical: list[HookedList] = []

    def make_canonical(value: list[int]) -> HookedList:
        result = HookedList(value)
        canonical.append(result)
        return result

    received: list[Any] = []
    summon = _scalar_service(
        Annotated[list[int], AfterValidator(make_canonical)], received
    )
    result = asyncio.run(summon._runtime.call(summon.endpoints[0], {"value": [3]}))

    assert result == Result(value=1)
    assert received == [[3]]
    assert received[0] is canonical[0]
    assert events == []


def test_direct_raw_input_rejects_invalid_nested_constructed_model_like_http():
    hooks: list[str] = []

    class Inner(BaseModel):
        x: int

        @field_serializer("x")
        def serialize_x(self, value: int) -> int:
            hooks.append("serialize")
            return value

        def __copy__(self):
            hooks.append("copy")
            return self

        def __deepcopy__(self, memo=None):
            hooks.append("deepcopy")
            return self

        def __repr__(self) -> str:
            hooks.append("repr")
            return "inner"

        def __eq__(self, other: object) -> bool:
            hooks.append("eq")
            return False

        def __hash__(self) -> int:
            hooks.append("hash")
            return 0

    class Request(BaseModel):
        value: Inner

    received: list[Any] = []

    def apply(value: Inner) -> Result:
        received.append(value.x)
        return Result(value=value.x)

    apply.__annotations__ = {"value": Inner, "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    raw = Summon("nested-direct-raw")

    def raw_endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one nested value."""
        ...

    raw_endpoint.__annotations__["request"] = Request
    raw("/nested")(raw_endpoint)

    invalid = Inner.model_construct(x="ATTACKER")
    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(raw.endpoints[0], {"value": invalid}))

    http = Summon("nested-direct-http")

    def http_endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one nested value."""
        ...

    http_endpoint.__annotations__["request"] = Request
    http("/nested")(http_endpoint)

    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/nested", json={"value": {"x": "ATTACKER"}}
    )
    assert response.status_code == 422
    assert received == []
    assert hooks == []


def test_agent_raw_input_rejects_invalid_nested_constructed_model_before_model():
    class Inner(BaseModel):
        x: int

    class Request(BaseModel):
        value: Inner

    class AgentResult(BaseModel):
        answer: int

    events: list[str] = []

    def apply(value: Inner) -> Result:
        events.append("operation")
        return Result(value=value.x)

    def model(messages, info):
        events.append("model")
        raise AssertionError("invalid input reached the model")

    apply.__annotations__ = {"value": Inner, "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)

    def service(name: str) -> Summon:
        summon = Summon(name)

        def endpoint(
            request: Any,
            result=Required(operation, calls=Exactly(1)),
        ) -> Any:
            """Apply one nested value through the agent path."""
            ...

        endpoint.__annotations__["request"] = Request
        endpoint.__annotations__["return"] = AgentResult
        summon("/nested")(endpoint)
        summon._runtime = Runtime(model=FunctionModel(model))
        return summon

    raw = service("nested-agent-raw")
    invalid = Inner.model_construct(x="ATTACKER")
    with pytest.raises(ValidationError):
        asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": invalid}))

    http = service("nested-agent-http")
    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/nested", json={"value": {"x": "ATTACKER"}}
    )
    assert response.status_code == 422
    assert events == []


def test_nested_constructed_model_and_request_validators_run_once_on_raw_admission():
    validations: list[str] = []

    class Inner(BaseModel):
        x: int

        @field_validator("x")
        @classmethod
        def validate_x(cls, value: int) -> int:
            validations.append("inner")
            return value + 1

    class Request(BaseModel):
        value: Inner

        @field_validator("value")
        @classmethod
        def validate_value(cls, value: Inner) -> Inner:
            validations.append("request")
            return value

    received: list[int] = []

    def apply(value: Inner) -> Result:
        received.append(value.x)
        return Result(value=value.x)

    apply.__annotations__ = {"value": Any, "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("nested-validator-once")

    def endpoint(
        request: Any,
        result=Required(operation, calls=Exactly(1)),
    ) -> Result:
        """Apply one structurally validated nested value."""
        ...

    endpoint.__annotations__["request"] = Request
    summon("/nested")(endpoint)

    result = asyncio.run(
        Runtime().call(summon.endpoints[0], {"value": Inner.model_construct(x=3)})
    )

    assert result.value == 4
    assert received == [4]
    assert validations == ["inner", "request"]


def test_parameterless_raw_input_rejects_undeclared_keys_before_hooks_or_model():
    events: list[str] = []

    class Evil:
        def __deepcopy__(self, memo):
            events.append("copy")
            return self

        def __repr__(self) -> str:
            events.append("repr")
            return "evil"

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            return False

        def __hash__(self) -> int:
            events.append("hash")
            return 0

    def model(messages, info):
        events.append("model")
        raise AssertionError("undeclared input reached the model")

    summon = Summon("parameterless-rejection")
    summon._runtime = Runtime(model=FunctionModel(model))

    @summon("/health")
    def health() -> str:
        """Report readiness."""
        ...

    with pytest.raises(ValidationError):
        asyncio.run(summon._runtime.call(summon.endpoints[0], {"undeclared": Evil()}))

    assert events == []


def test_parameterless_empty_input_reaches_agent_for_raw_and_http():
    calls: list[str] = []

    def model(messages, info):
        calls.append("model")
        return ModelResponse(parts=[TextPart("ready")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        @summon("/health")
        def health() -> str:
            """Report readiness."""
            ...

        return summon

    raw = service("parameterless-empty-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], {})) == "ready"

    http = service("parameterless-empty-http")
    response = TestClient(build_app(http)).post("/health")
    assert response.status_code == 200, response.text
    assert response.json() == "ready"
    assert calls == ["model", "model"]


def test_raw_agent_prompt_projects_nested_models_like_http_without_hooks():
    hooks: list[str] = []
    prompts: list[str] = []

    class Inner(BaseModel):
        x: int

        def __copy__(self):
            hooks.append("copy")
            return self

        def __deepcopy__(self, memo=None):
            hooks.append("deepcopy")
            return self

        def __repr__(self) -> str:
            hooks.append("repr")
            return "lossy"

        def __eq__(self, other: object) -> bool:
            hooks.append("eq")
            return False

        def __hash__(self) -> int:
            hooks.append("hash")
            return 0

    class Request(BaseModel):
        value: Inner

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Inspect one nested request value."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/nested-prompt")(endpoint)
        return summon

    raw = service("nested-prompt-raw")
    assert (
        asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": Inner(x=23)}))
        == "done"
    )

    http = service("nested-prompt-http")
    response = TestClient(build_app(http)).post(
        "/nested-prompt", json={"value": {"x": 23}}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: {"x": 23}' in prompts[0]
    assert hooks == []


def test_raw_and_http_prompts_omit_statically_excluded_fields_without_hooks():
    hooks: list[str] = []
    prompts: list[str] = []
    received: list[tuple[str, str]] = []

    class Inner(BaseModel):
        visible: int
        empty_alias: int = Field(alias="")
        secret: str = Field(exclude=True)

        @field_serializer("secret")
        def serialize_secret(self, value: str) -> str:
            hooks.append("nested serializer")
            raise RuntimeError("nested secret serializer")

    class Request(BaseModel):
        visible: int
        secret: str = Field(exclude=True)
        nested: Inner

        @field_serializer("secret")
        def serialize_secret(self, value: str) -> str:
            hooks.append("top serializer")
            raise RuntimeError("top secret serializer")

    class Applied(BaseModel):
        value: int

    def apply(secret: str, nested: Inner) -> Applied:
        received.append((secret, nested.secret))
        return Applied(value=nested.visible)

    apply.__annotations__ = {
        "secret": str,
        "nested": Inner,
        "return": Applied,
    }
    operation = Operation(
        apply,
        bind={
            "secret": FromRequest("secret"),
            "nested": FromRequest("nested"),
        },
        output=Applied,
    )

    def service(name: str) -> Summon:
        turns = 0

        def model(messages, info):
            nonlocal turns
            turns += 1
            if turns == 1:
                prompt = next(
                    part.content
                    for message in messages
                    for part in message.parts
                    if isinstance(part, UserPromptPart)
                )
                assert type(prompt) is str
                prompts.append(prompt)
                return ModelResponse(parts=[ToolCallPart("apply", {})])
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"value": 23})]
            )

        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(
            request: Any,
            result=Required(operation, calls=Exactly(1)),
        ) -> Result:
            """Inspect a request without exposing excluded input fields."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/excluded-prompt")(endpoint)
        return summon

    body = {
        "visible": 7,
        "secret": "top-secret",
        "nested": {"visible": 23, "": 11, "secret": "nested-secret"},
    }
    raw = service("excluded-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == Result(value=23)

    http = service("excluded-prompt-http")
    response = TestClient(build_app(http)).post("/excluded-prompt", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 23}
    assert prompts == [
        "Endpoint: /excluded-prompt\nParameters:\n  visible: 7\n  nested: "
        '{"visible": 23, "": 11}',
        "Endpoint: /excluded-prompt\nParameters:\n  visible: 7\n  nested: "
        '{"visible": 23, "": 11}',
    ]
    assert received == [
        ("top-secret", "nested-secret"),
        ("top-secret", "nested-secret"),
    ]
    assert hooks == []


def test_raw_prompt_projects_runtime_subclasses_through_declared_nested_schemas():
    prompts: list[str] = []
    hooks: list[str] = []
    marker = "PRIVATE_CREDENTIAL_MARKER"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

        def __getattribute__(self, name: str) -> Any:
            if name in {"visible", "credential"}:
                hooks.append(f"attribute:{name}")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class Request(BaseModel):
        value: Public
        nested: list[dict[str, Public | None]]

        @field_validator("value", "nested", mode="after")
        @classmethod
        def return_runtime_subclasses(cls, value: Any) -> Any:
            if isinstance(value, Public):
                return Private(visible=value.visible, credential=marker)
            return [
                {
                    key: (
                        Private(visible=item.visible, credential=marker)
                        if item is not None
                        else None
                    )
                    for key, item in group.items()
                }
                for group in value
            ]

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Inspect values through their declared public request schema."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/declared-schema-prompt")(endpoint)
        return summon

    body = {
        "value": {"visible": 1},
        "nested": [{"first": {"visible": 2}, "empty": None}],
    }
    raw = service("declared-schema-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == "done"

    http = service("declared-schema-prompt-http")
    response = TestClient(build_app(http)).post("/declared-schema-prompt", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert '  value: {"visible": 1}' in prompts[0]
    assert '  nested: [{"first": {"visible": 2}, "empty": null}]' in prompts[0]
    assert hooks == []


def test_raw_prompt_projects_typed_dict_fields_through_declared_schemas():
    prompts: list[str] = []
    hooks: list[str] = []
    marker = "TYPED_DICT_PRIVATE_CREDENTIAL"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

        def __getattribute__(self, name: str) -> Any:
            if name in {"visible", "credential"}:
                hooks.append(f"attribute:{name}")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class Wrapped(TypedDict):
        child: Public

    class Request(BaseModel):
        value: Wrapped

        @field_validator("value", mode="after")
        @classmethod
        def return_runtime_subclass(cls, value: Wrapped) -> Wrapped:
            return {
                "child": Private(
                    visible=value["child"].visible,
                    credential=marker,
                )
            }

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Inspect a TypedDict through its declared public field schema."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/typed-dict-prompt")(endpoint)
        return summon

    body = {"value": {"child": {"visible": 23}}}
    raw = service("typed-dict-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == "done"

    http = service("typed-dict-prompt-http")
    response = TestClient(build_app(http)).post("/typed-dict-prompt", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert '  value: {"child": {"visible": 23}}' in prompts[0]
    assert hooks == []


def test_typed_dict_union_rejects_hostile_keys_without_equality_hooks():
    hooks: list[str] = []
    model_calls: list[str] = []

    class Public(BaseModel):
        visible: int

    class Wrapped(TypedDict):
        child: Public

    class HostileKey:
        def __hash__(self) -> int:
            return hash("child")

        def __eq__(self, other: object) -> bool:
            hooks.append("eq")
            raise AssertionError("application equality must not run")

        def __repr__(self) -> str:
            hooks.append("repr")
            raise AssertionError("application repr must not run")

    class Request(BaseModel):
        value: Wrapped | int

        @field_validator("value", mode="after")
        @classmethod
        def replace_with_hostile_storage(cls, value: Wrapped | int) -> Wrapped | int:
            result = {HostileKey(): Public(visible=23)}
            hooks.clear()
            return result  # type: ignore[return-value]

    def model(messages, info):
        model_calls.append("model")
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Reject incompatible TypedDict union storage without application hooks."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/typed-dict-union-prompt")(endpoint)
        return summon

    body = {"value": {"child": {"visible": 23}}}
    raw = service("typed-dict-union-hostile-raw")
    with pytest.raises(ValidationError):
        asyncio.run(raw._runtime.call(raw.endpoints[0], body))

    http = service("typed-dict-union-hostile-http")
    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/typed-dict-union-prompt", json=body
    )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert hooks == []
    assert model_calls == []


def test_raw_prompt_selects_container_union_by_declared_item_schema():
    prompts: list[str] = []
    hooks: list[str] = []
    marker = "CONTAINER_UNION_PRIVATE_CREDENTIAL"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

        def __getattribute__(self, name: str) -> Any:
            if name in {"visible", "credential"}:
                hooks.append(f"attribute:{name}")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class Request(BaseModel):
        value: list[int] | list[Public]

        @field_validator("value", mode="after")
        @classmethod
        def return_runtime_subclasses(
            cls, value: list[int] | list[Public]
        ) -> list[int] | list[Public]:
            if value and isinstance(value[0], Public):
                return [
                    Private(visible=item.visible, credential=marker)
                    for item in value
                    if isinstance(item, Public)
                ]
            return value

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Inspect a container union through its applicable declared branch."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/container-union-prompt")(endpoint)
        return summon

    body = {"value": [{"visible": 23}]}
    raw = service("container-union-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == "done"

    http = service("container-union-prompt-http")
    response = TestClient(build_app(http)).post("/container-union-prompt", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert '  value: [{"visible": 23}]' in prompts[0]
    assert hooks == []


def test_empty_container_union_keeps_raw_and_http_prompt_parity():
    prompts: list[str] = []

    class Public(BaseModel):
        visible: int

    class Request(BaseModel):
        value: list[int] | list[Public]

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Project an empty container through the declared union contract."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/empty-container-union")(endpoint)
        return summon

    body = {"value": []}
    raw = service("empty-container-union-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == "done"

    http = service("empty-container-union-http")
    response = TestClient(build_app(http)).post("/empty-container-union", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert "  value: []" in prompts[0]


def test_literal_union_keeps_raw_and_http_prompt_parity():
    prompts: list[str] = []

    class Request(BaseModel):
        value: Literal["safe"] | int

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Project a literal through the declared union contract."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/literal-union")(endpoint)
        return summon

    body = {"value": "safe"}
    raw = service("literal-union-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == "done"

    http = service("literal-union-http")
    response = TestClient(build_app(http)).post("/literal-union", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: "safe"' in prompts[0]


def test_nested_model_empty_alias_is_preserved_in_raw_and_http_prompts():
    prompts: list[str] = []

    class Inner(BaseModel):
        x: int = Field(alias="")

    class Request(BaseModel):
        value: Inner

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Inspect a nested request with an empty field alias."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/empty-alias-prompt")(endpoint)
        return summon

    raw = service("empty-alias-prompt-raw")
    assert (
        asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": {"": 23}})) == "done"
    )

    http = service("empty-alias-prompt-http")
    response = TestClient(build_app(http)).post(
        "/empty-alias-prompt", json={"value": {"": 23}}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: {"": 23}' in prompts[0]


def test_nested_model_dict_descriptor_is_bypassed_for_raw_and_http_prompts():
    hooks: list[str] = []
    prompts: list[str] = []
    base_descriptor = BaseModel.__dict__["__dict__"]

    class HostileDictDescriptor:
        def __get__(self, instance, owner=None):
            hooks.append("__dict__ descriptor")
            raise RuntimeError("application __dict__ descriptor")

        def __set__(self, instance, value):
            base_descriptor.__set__(instance, value)

    class Inner(BaseModel):
        x: int
        __dict__ = HostileDictDescriptor()  # pyright: ignore[reportGeneralTypeIssues]

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        annotation = Annotated[int, AfterValidator(lambda value: Inner(x=value))]

        def endpoint(value: Any) -> str:
            """Inspect a model without dispatching its storage descriptor."""
            ...

        endpoint.__annotations__["value"] = annotation
        summon("/dict-descriptor-prompt", method="GET")(endpoint)

        return summon

    raw = service("dict-descriptor-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": 23})) == "done"

    http = service("dict-descriptor-prompt-http")
    response = TestClient(build_app(http)).get(
        "/dict-descriptor-prompt", params={"value": "23"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: {"x": 23}' in prompts[0]
    assert hooks == []


def test_nested_model_hostile_dict_subclass_is_unavailable_for_raw_and_http_prompts():
    hooks: list[str] = []
    prompts: list[str] = []
    base_descriptor = BaseModel.__dict__["__dict__"]

    class HostileDict(dict):
        def __contains__(self, key):
            hooks.append("contains")
            raise RuntimeError("application contains")

        def __getitem__(self, key):
            hooks.append("getitem")
            raise RuntimeError("application getitem")

        def __iter__(self):
            hooks.append("iter")
            raise RuntimeError("application iter")

        def items(self):
            hooks.append("items")
            raise RuntimeError("application items")

    class Inner(BaseModel):
        x: int

        def __init__(self, **data: Any):
            super().__init__(**data)
            base_descriptor.__set__(self, HostileDict(x=data["x"]))

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))
        annotation = Annotated[int, AfterValidator(lambda value: Inner(x=value))]

        def endpoint(value: Any) -> str:
            """Inspect a model without dispatching hostile storage hooks."""
            ...

        endpoint.__annotations__["value"] = annotation
        summon("/hostile-dict-storage-prompt", method="GET")(endpoint)
        return summon

    raw = service("hostile-dict-storage-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": 23})) == "done"

    http = service("hostile-dict-storage-prompt-http")
    response = TestClient(build_app(http)).get(
        "/hostile-dict-storage-prompt", params={"value": "23"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: "<unavailable>"' in prompts[0]
    assert hooks == []


def test_nested_model_extra_descriptor_is_bypassed_for_raw_and_http_prompts():
    hooks: list[str] = []
    prompts: list[str] = []
    base_descriptor = BaseModel.__dict__["__pydantic_extra__"]

    class HostileExtraDescriptor:
        def __get__(self, instance, owner=None):
            hooks.append("__pydantic_extra__ descriptor")
            raise RuntimeError("application __pydantic_extra__ descriptor")

        def __set__(self, instance, value):
            base_descriptor.__set__(instance, value)

    class Inner(BaseModel):
        x: int
        __pydantic_extra__ = HostileExtraDescriptor()  # pyright: ignore[reportGeneralTypeIssues]

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))
        annotation = Annotated[int, AfterValidator(lambda value: Inner(x=value))]

        def endpoint(value: Any) -> str:
            """Inspect a model without dispatching its extra-storage descriptor."""
            ...

        endpoint.__annotations__["value"] = annotation
        summon("/extra-descriptor-prompt", method="GET")(endpoint)
        return summon

    raw = service("extra-descriptor-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": 23})) == "done"

    http = service("extra-descriptor-prompt-http")
    response = TestClient(build_app(http)).get(
        "/extra-descriptor-prompt", params={"value": "23"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: {"x": 23}' in prompts[0]
    assert hooks == []


@pytest.mark.parametrize("container_type", [set, frozenset])
def test_hashed_container_of_nested_models_projects_for_raw_and_http(
    container_type: Any,
):
    prompts: list[str] = []
    hooks: list[str] = []

    class HostileModelMeta(type(BaseModel)):
        def __getattribute__(cls, name):
            if name == "model_fields":
                hooks.append("metaclass getattribute")
                raise RuntimeError("metaclass getattribute")
            return super().__getattribute__(name)

    class Inner(BaseModel, metaclass=HostileModelMeta):
        model_config = {"frozen": True}

        x: int

    Request = create_model("Request", value=(container_type[Inner], ...))

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Inspect a hashed container of nested request values."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/nested-set-prompt")(endpoint)
        return summon

    raw = service(f"nested-{container_type.__name__}-prompt-raw")
    assert (
        asyncio.run(raw._runtime.call(raw.endpoints[0], {"value": [{"x": 23}]}))
        == "done"
    )

    http = service(f"nested-{container_type.__name__}-prompt-http")
    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/nested-set-prompt", json={"value": [{"x": 23}]}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert prompts[0] == prompts[1]
    assert '  value: [{"x": 23}]' in prompts[0]
    assert hooks == []


def test_raw_request_projection_bypasses_model_metadata_and_attribute_hooks():
    armed = [False]
    hooks: list[str] = []

    class HostileModelMeta(type(BaseModel)):
        def __getattribute__(cls, name):
            if armed[0] and name == "model_fields":
                hooks.append("metaclass getattribute")
                raise RuntimeError("metaclass getattribute")
            return super().__getattribute__(name)

    class Request(BaseModel, metaclass=HostileModelMeta):
        value: int

        def __getattribute__(self, name):
            if armed[0] and name in {"value", "__pydantic_extra__"}:
                hooks.append(f"instance getattribute: {name}")
                raise RuntimeError("instance getattribute")
            return super().__getattribute__(name)

    def model(messages, info):
        return ModelResponse(parts=[TextPart("done")])

    summon = Summon("hostile-request-projection")
    summon._runtime = Runtime(model=FunctionModel(model))

    def endpoint(request: Any) -> str:
        """Inspect a request without application attribute hooks."""
        ...

    endpoint.__annotations__["request"] = Request
    summon("/hostile-request")(endpoint)
    armed[0] = True

    assert (
        asyncio.run(summon._runtime.call(summon.endpoints[0], {"value": 23})) == "done"
    )
    assert hooks == []


@pytest.mark.parametrize("dataclass_options", [{}, {"frozen": True}, {"slots": True}])
def test_dataclass_prompt_projection_matches_http_without_losing_identity(
    dataclass_options: dict[str, bool],
):
    prompts: list[str] = []
    canonical: list[Any] = []
    received: list[Any] = []

    @dataclass(**dataclass_options)
    class Box:
        value: Annotated[int, Field(serialization_alias="v")]
        hidden: Annotated[str, Field(exclude=True)] = "hidden"

    PrivateBox = make_dataclass(
        "PrivateBox",
        [("credential", str, field(default="PRIVATE_DATACLASS_MARKER"))],
        bases=(Box,),
        frozen=dataclass_options.get("frozen", False),
        slots=dataclass_options.get("slots", False),
    )

    class Request(BaseModel):
        box: Box
        nested: list[dict[str, Box]]

        @field_validator("box", mode="after")
        @classmethod
        def use_runtime_subclass(cls, value: Box) -> Box:
            result = PrivateBox(value.value, value.hidden)
            canonical.append(result)
            return result

        @field_validator("nested", mode="after")
        @classmethod
        def use_nested_runtime_subclasses(
            cls, value: list[dict[str, Box]]
        ) -> list[dict[str, Box]]:
            return [
                {
                    key: PrivateBox(item.value, item.hidden)
                    for key, item in group.items()
                }
                for group in value
            ]

    class AgentResult(BaseModel):
        answer: int

    def apply(box: Any) -> Result:
        received.append(box)
        return Result(value=box.value)

    apply.__annotations__ = {"box": InstanceOf[Box], "return": Result}
    operation = Operation(apply, bind={"box": FromRequest("box")}, output=Result)

    def service(name: str) -> Summon:
        turns = 0

        def model(messages, info):
            nonlocal turns
            turns += 1
            if turns == 1:
                prompt = next(
                    part.content
                    for message in messages
                    for part in message.parts
                    if isinstance(part, UserPromptPart)
                )
                assert type(prompt) is str
                prompts.append(prompt)
                return ModelResponse(parts=[ToolCallPart("apply", {})])
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"answer": 7})]
            )

        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(
            request: Any,
            result=Required(operation, calls=Exactly(1)),
        ) -> AgentResult:
            """Project declared dataclass fields into the model prompt."""
            ...

        endpoint.__annotations__["request"] = Request
        endpoint.__annotations__["return"] = AgentResult
        summon("/dataclass-prompt")(endpoint)
        return summon

    body = {
        "box": {"value": 7, "hidden": "secret"},
        "nested": [{"first": {"value": 8, "hidden": "nested-secret"}}],
    }
    raw = service("dataclass-prompt-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == AgentResult(
        answer=7
    )

    http = service("dataclass-prompt-http")
    response = TestClient(build_app(http)).post("/dataclass-prompt", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == {"answer": 7}
    assert prompts[0] == prompts[1]
    assert '  box: {"v": 7}' in prompts[0]
    assert '  nested: [{"first": {"v": 8}}]' in prompts[0]
    assert "PRIVATE_DATACLASS_MARKER" not in prompts[0]
    assert "credential" not in prompts[0]
    assert "hidden" not in prompts[0]
    assert received[0] is canonical[0]
    assert received[1] is canonical[1]


@pytest.mark.parametrize("dataclass_options", [{}, {"frozen": True}, {"slots": True}])
def test_dataclass_prompt_projection_bypasses_application_hooks(
    dataclass_options: dict[str, bool],
):
    hooks: list[str] = []
    prompts: list[str] = []

    @dataclass(**dataclass_options)
    class Box:
        value: int

        def __getattribute__(self, name: str) -> Any:
            if name in {"value", "__dict__"}:
                hooks.append(f"attribute:{name}")
                raise RuntimeError("application attribute")
            return object.__getattribute__(self, name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

        def __copy__(self):
            hooks.append("copy")
            raise RuntimeError("application copy")

        def __deepcopy__(self, memo):
            hooks.append("deepcopy")
            raise RuntimeError("application deepcopy")

        def __eq__(self, other: object) -> bool:
            hooks.append("eq")
            raise RuntimeError("application equality")

        def __hash__(self) -> int:
            hooks.append("hash")
            raise RuntimeError("application hash")

        @field_serializer("value")
        def serialize_value(self, value: int) -> str:
            hooks.append("serialize")
            raise RuntimeError("application serializer")

    class Request(BaseModel):
        box: Box

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Project a dataclass without application callbacks."""
            ...

        endpoint.__annotations__["request"] = Request
        summon("/hostile-dataclass-prompt")(endpoint)
        return summon

    raw = service("hostile-dataclass-prompt-raw")
    assert (
        asyncio.run(raw._runtime.call(raw.endpoints[0], {"box": {"value": 7}}))
        == "done"
    )

    assert '  box: {"value": 7}' in prompts[0]
    assert hooks == []


def _raw_http_agent_prompts(
    request_model: type[BaseModel], body: dict[str, Any], path: str
) -> list[str]:
    prompts: list[str] = []

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("done")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        def endpoint(request: Any) -> str:
            """Project the validated request through its declared public schema."""
            ...

        endpoint.__annotations__["request"] = request_model
        summon(path)(endpoint)
        return summon

    raw = service(f"{path}-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], body)) == "done"

    http = service(f"{path}-http")
    response = TestClient(build_app(http)).post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json() == "done"
    assert len(prompts) == 2
    assert prompts[0] == prompts[1]
    return prompts


def test_typed_model_extras_project_through_declared_value_schema_without_hooks():
    hooks: list[str] = []
    marker = "TYPED_MODEL_EXTRA_PRIVATE_CREDENTIAL"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

        def __getattribute__(self, name: str) -> Any:
            if name in {"visible", "credential"}:
                hooks.append(f"attribute:{name}")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class Request(BaseModel):
        model_config = ConfigDict(extra="allow")
        __pydantic_extra__: dict[str, Public] = Field(  # type: ignore[reportIncompatibleVariableOverride]
            init=False
        )

        @model_validator(mode="after")
        def replace_extra_with_runtime_subclass(self) -> Request:
            storage = BaseModel.__dict__["__dict__"].__get__(self, type(self))
            assert type(storage) is dict
            extras = dict.__getitem__(storage, "__pydantic_extra__")
            assert type(extras) is dict
            dict.__setitem__(
                extras,
                "note",
                Private(visible=23, credential=marker),
            )
            return self

    prompts = _raw_http_agent_prompts(
        Request,
        {"note": {"visible": 23}},
        "/typed-model-extra-prompt",
    )

    assert '  note: {"visible": 23}' in prompts[0]
    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert hooks == []


def test_selected_union_branch_resolves_nullable_reference_wrappers_without_hooks():
    hooks: list[str] = []
    marker = "WRAPPED_UNION_PRIVATE_CREDENTIAL"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

        def __getattribute__(self, name: str) -> Any:
            if name in {"visible", "credential"}:
                hooks.append(f"attribute:{name}")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class Request(BaseModel):
        value: Annotated[Public | None, Field(description="public value")] | int

        @field_validator("value", mode="after")
        @classmethod
        def replace_with_runtime_subclass(cls, value: Public | int | None) -> Any:
            if isinstance(value, Public):
                return Private(visible=23, credential=marker)
            return value

    prompts = _raw_http_agent_prompts(
        Request,
        {"value": {"visible": 23}},
        "/wrapped-union-prompt",
    )

    assert '  value: {"visible": 23}' in prompts[0]
    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert hooks == []


def test_typed_dict_union_selection_requires_declared_required_fields():
    class Left(TypedDict):
        a: int

    class Right(TypedDict):
        b: int

    class Request(BaseModel):
        value: Left | Right

    prompts = _raw_http_agent_prompts(
        Request,
        {"value": {"b": 2}},
        "/required-typed-dict-union-prompt",
    )

    assert '  value: {"b": 2}' in prompts[0]


def test_root_model_projects_its_declared_root_schema_without_hooks():
    hooks: list[str] = []
    marker = "ROOT_MODEL_PRIVATE_CREDENTIAL"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

        def __getattribute__(self, name: str) -> Any:
            if name in {"visible", "credential"}:
                hooks.append(f"attribute:{name}")
            return super().__getattribute__(name)

        def __repr__(self) -> str:
            hooks.append("repr")
            raise RuntimeError("application repr")

    class PublicRoot(RootModel[Public]):
        pass

    class Request(BaseModel):
        value: PublicRoot

        @field_validator("value", mode="after")
        @classmethod
        def replace_root_with_runtime_subclass(cls, value: PublicRoot) -> PublicRoot:
            return PublicRoot.model_construct(
                root=Private(visible=23, credential=marker)
            )

    prompts = _raw_http_agent_prompts(
        Request,
        {"value": {"visible": 23}},
        "/root-model-prompt",
    )

    assert '  value: {"visible": 23}' in prompts[0]
    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert hooks == []


def test_typed_dict_with_allowed_extras_retains_admitted_values_in_prompt():
    class OpenPayload(TypedDict):
        __pydantic_config__ = ConfigDict(  # pyright: ignore[reportGeneralTypeIssues]
            extra="allow"
        )
        count: int

    class Request(BaseModel):
        value: OpenPayload

    prompts = _raw_http_agent_prompts(
        Request,
        {"value": {"count": 1, "note": "admitted"}},
        "/open-typed-dict-prompt",
    )

    assert '  value: {"count": 1, "note": "admitted"}' in prompts[0]


def test_enum_union_projection_matches_http_without_application_hooks():
    hooks: list[str] = []

    class Color(str, Enum):  # noqa: UP042 - regression covers classic str Enum
        red = "red"

        def __eq__(self, other: object) -> bool:
            hooks.append("equality")
            return str.__eq__(self, other)

        def __hash__(self) -> int:
            hooks.append("hash")
            return str.__hash__(self)

        def __str__(self) -> str:
            hooks.append("serialization")
            return str.__str__(self)

    class DirectRequest(BaseModel):
        value: Color | int

        @model_validator(mode="after")
        def start_projection_probe(self) -> DirectRequest:
            hooks.clear()
            return self

    class Wrapped(TypedDict):
        color: Color

    class WrappedRequest(BaseModel):
        value: Wrapped | int

        @model_validator(mode="after")
        def start_projection_probe(self) -> WrappedRequest:
            hooks.clear()
            return self

    direct_prompts = _raw_http_agent_prompts(
        DirectRequest, {"value": "red"}, "/enum-union-prompt"
    )
    wrapped_prompts = _raw_http_agent_prompts(
        WrappedRequest,
        {"value": {"color": "red"}},
        "/typed-dict-enum-union-prompt",
    )

    assert '  value: "red"' in direct_prompts[0]
    assert '  value: {"color": "red"}' in wrapped_prompts[0]
    assert hooks == []


def test_deep_recursive_union_projection_is_bounded_and_matches_http():
    class Request(BaseModel):
        value: RecursiveJson

    value: Any = 1
    for _ in range(200):
        value = [value]

    prompts = _raw_http_agent_prompts(
        Request, {"value": value}, "/deep-recursive-union-prompt"
    )

    assert "<unavailable>" in prompts[0]


def test_nested_nullable_union_budget_cannot_select_private_runtime_branch():
    marker = "NESTED_NULLABLE_PRIVATE_CREDENTIAL"

    class Public(BaseModel):
        visible: int

    class Private(Public):
        credential: str

    left: Any = int
    right: Any = Public
    public_value: Any = {"visible": 1}
    private_value: Any = Private(visible=1, credential=marker)
    for _ in range(34):
        left = list[left | None]
        right = list[right | None]
        public_value = [public_value]
        private_value = [private_value]

    @field_validator("value", mode="after")
    @classmethod
    def replace_with_private_runtime_subclass(cls, value: Any) -> Any:
        return private_value

    Request = create_model(
        "NestedNullableCompetingUnionRequest",
        value=(left | right, ...),
        __validators__={
            "replace_with_private_runtime_subclass": replace_with_private_runtime_subclass
        },
    )

    prompts = _raw_http_agent_prompts(
        Request,
        {"value": public_value},
        "/nested-nullable-competing-union-prompt",
    )

    assert marker not in prompts[0]
    assert "credential" not in prompts[0]
    assert '"visible": 1' in prompts[0]


@pytest.mark.parametrize(
    "parameter_name",
    [
        "model_config",
        "model_fields",
        "model_computed_fields",
        "model_extra",
        "__base__",
        "__config__",
        "__validators__",
        "__cls_kwargs__",
        "_value",
        "_private_name",
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_reserved_parameter_names_register_and_match_raw_http_contract(
    parameter_name: str, method: str
):
    prompts: list[str] = []

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("ready")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))
        namespace: dict[str, Any] = {}
        exec(
            compile(
                f"def endpoint({parameter_name}: int) -> str:\n    return Ellipsis\n",
                "<reserved-parameter>",
                "exec",
                dont_inherit=True,
            ),
            namespace,
        )
        endpoint = namespace["endpoint"]
        endpoint.__doc__ = "Inspect one reserved-name parameter."
        summon("/reserved", method=method)(endpoint)
        return summon

    raw = service(f"reserved-{parameter_name}-{method.lower()}-raw")
    assert (
        asyncio.run(raw._runtime.call(raw.endpoints[0], {parameter_name: "7"}))
        == "ready"
    )

    http = service(f"reserved-{parameter_name}-{method.lower()}-http")
    client = TestClient(build_app(http))
    response = (
        client.get("/reserved", params={parameter_name: "7"})
        if method == "GET"
        else client.post("/reserved", json={parameter_name: "7"})
    )

    assert response.status_code == 200, response.text
    assert response.json() == "ready"
    assert prompts[0] == prompts[1]
    assert f"  {parameter_name}: 7" in prompts[0]


def test_reserved_internal_names_stay_stable_across_path_and_body_models():
    prompts: list[str] = []

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert type(prompt) is str
        prompts.append(prompt)
        return ModelResponse(parts=[TextPart("ready")])

    def service(name: str) -> Summon:
        summon = Summon(name)
        summon._runtime = Runtime(model=FunctionModel(model))

        @summon("/items/{item_id}", method="POST")
        def endpoint(item_id: int, model_config: int, summonpot_field_0: int) -> str:
            """Inspect path and body parameters with colliding public names."""
            ...

        return summon

    values = {"item_id": "1", "model_config": "2", "summonpot_field_0": "3"}
    raw = service("reserved-path-body-raw")
    assert asyncio.run(raw._runtime.call(raw.endpoints[0], values)) == "ready"

    http = service("reserved-path-body-http")
    response = TestClient(build_app(http)).post(
        "/items/1", json={"model_config": "2", "summonpot_field_0": "3"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == "ready"
    for prompt in prompts:
        assert "  item_id: 1" in prompt
        assert "  model_config: 2" in prompt
        assert "  summonpot_field_0: 3" in prompt
