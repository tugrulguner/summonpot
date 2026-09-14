"""Raw Runtime.call inputs match generated HTTP request semantics."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import pytest
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app


class Result(BaseModel):
    value: int


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

    invalid = Inner.model_construct(x="ATTACKER")
    with pytest.raises(ValidationError):
        asyncio.run(Runtime().call(summon.endpoints[0], {"value": invalid}))

    assert len(initializations) == 1
    assert initializations[0] is invalid
    assert operation_calls == []
    assert hooks == []


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
