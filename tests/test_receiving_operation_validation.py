"""Receiving operation contracts validate injected values before invocation."""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

import pytest
from annotated_types import MultipleOf
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    PlainSerializer,
    PlainValidator,
    Tag,
    TypeAdapter,
    ValidationError,
    WrapValidator,
    field_validator,
)
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_core import core_schema

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import _registered_plan, _validated_transport_request
from summonpot.runtime import Runtime, _OperationInputError
from summonpot.server import build_app


class Result(BaseModel):
    value: int


class BroadRequest(BaseModel):
    value: int


class AnyRequest(BaseModel):
    value: Any


CANONICAL_VALUES: list[list[int]] = []


def remember_canonical(value: list[int]) -> list[int]:
    CANONICAL_VALUES.append(value)
    return value


def test_direct_path_rejects_a_request_value_outside_the_receiving_constraint():
    starts = 0

    def apply(value: Annotated[int, Field(gt=10)]) -> Result:
        nonlocal starts
        starts += 1
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("receiving-contract")

    @summon("/apply")
    def endpoint(
        request: BroadRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Apply a value accepted by the receiving operation."""
        ...

    with pytest.raises(RuntimeError, match="receiving parameter contract"):
        asyncio.run(
            Runtime(model="invalid-provider:no-model").call(
                summon.endpoints[0], {"value": 5}
            )
        )

    assert starts == 0


def test_transforming_receiver_is_rejected_instead_of_coercing_an_injected_value():
    starts = 0

    def apply(value: Annotated[int, BeforeValidator(int)]) -> Result:
        nonlocal starts
        starts += 1
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("strict-receiving-contract")

    with pytest.raises(TypeError, match="functional validator"):

        @summon("/apply")
        def endpoint(
            request: AnyRequest, result=Required(operation, calls=Exactly(1))
        ) -> Result:
            """Never coerce a canonical request value for the operation."""
            ...

    assert starts == 0


def test_receiver_validator_that_could_launder_a_same_type_value_is_rejected():
    starts = 0

    def apply(
        value: Annotated[int, Field(gt=10), BeforeValidator(lambda value: 11)],
    ) -> Result:
        nonlocal starts
        starts += 1
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("same-type-receiving-contract")

    with pytest.raises(TypeError, match="functional validator"):

        @summon("/apply")
        def endpoint(
            request: BroadRequest, result=Required(operation, calls=Exactly(1))
        ) -> Result:
            """Validate the canonical value rather than a transformed substitute."""
            ...

    assert starts == 0


def test_receiver_validator_before_a_later_constraint_is_rejected():
    starts = 0

    def apply(
        value: Annotated[int, BeforeValidator(lambda value: 11), Field(gt=10)],
    ) -> Result:
        nonlocal starts
        starts += 1
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("ordered-receiving-contract")

    with pytest.raises(TypeError, match="functional validator"):

        @summon("/apply")
        def endpoint(
            request: BroadRequest, result=Required(operation, calls=Exactly(1))
        ) -> Result:
            """Apply every receiving constraint to the canonical request value."""
            ...

    assert starts == 0


def test_after_validator_receiver_is_rejected_without_rerunning_request_validation():
    validated_requests: list[int] = []
    received: list[int] = []

    class Request(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def observe(cls, value: int) -> int:
            validated_requests.append(value)
            return value

    def apply(
        value: Annotated[int, Field(gt=10), AfterValidator(lambda value: value + 1)],
    ) -> Result:
        received.append(value)
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("canonical-receiving-contract")
    # A local model must be installed as the live annotation because this test module
    # uses postponed annotations.
    endpoint_annotations = {"request": Request, "return": Result}

    def endpoint(request, result=Required(operation, calls=Exactly(1))):
        """Preserve the canonical request value after checking the receiver."""
        ...

    endpoint.__annotations__ = endpoint_annotations
    with pytest.raises(TypeError, match="functional validator"):
        summon("/apply")(endpoint)

    assert validated_requests == []
    assert received == []


def test_http_receiving_check_does_not_rerun_request_model_validators():
    validations = 0

    class Request(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def observe(cls, value: int) -> int:
            nonlocal validations
            validations += 1
            return value

    def apply(value: Annotated[int, Field(gt=10)]) -> Result:
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("single-validation-receiving-contract")

    def endpoint(request, result=Required(operation, calls=Exactly(1))):
        """Validate the request once at the HTTP boundary."""
        ...

    endpoint.__annotations__ = {"request": Request, "return": Result}
    summon("/apply")(endpoint)

    response = TestClient(build_app(summon)).post("/apply", json={"value": 12})

    assert response.status_code == 200
    assert response.json() == {"value": 12}
    assert validations == 1


def test_valid_receiving_check_preserves_canonical_object_identity():
    CANONICAL_VALUES.clear()
    received: list[list[int]] = []

    class Request(BaseModel):
        value: Annotated[list[int], AfterValidator(remember_canonical)]

    def apply(value: Annotated[list[int], Field(min_length=1)]) -> Result:
        received.append(value)
        return Result(value=len(value))

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("identity-receiving-contract")

    def endpoint(request, result=Required(operation, calls=Exactly(1))):
        """Pass the canonical validated object to application code."""
        ...

    endpoint.__annotations__ = {"request": Request, "return": Result}
    summon("/apply")(endpoint)
    result = asyncio.run(
        Runtime(model="invalid-provider:no-model").call(
            summon.endpoints[0], {"value": [12]}
        )
    )

    assert result == Result(value=1)
    assert received[0] is CANONICAL_VALUES[0]


def test_is_instance_check_uses_no_value_comparison_or_rendering_hooks():
    events: list[str] = []
    received: list[Any] = []

    class Payload:
        @classmethod
        def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
            return core_schema.is_instance_schema(cls)

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            raise AssertionError("equality must not run")

        def __deepcopy__(self, memo: dict[int, Any]) -> Any:
            events.append("copy")
            raise AssertionError("copy must not run")

        def __repr__(self) -> str:
            events.append("repr")
            raise AssertionError("repr must not run")

        def __str__(self) -> str:
            events.append("str")
            raise AssertionError("str must not run")

    canonical = Payload()

    def serialize(value: Payload) -> str:
        events.append("serialize")
        raise AssertionError("serialization must not run")

    def apply(value: Any) -> Result:
        received.append(value)
        return Result(value=1)

    apply.__annotations__ = {
        "value": Annotated[Payload, PlainSerializer(serialize)],
        "return": Result,
    }
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("hook-free-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: AnyRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Check the canonical value without invoking application object hooks."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    carrier = _validated_transport_request(
        plan, {"value": "<unavailable>"}, typed={"value": canonical}
    )
    result = asyncio.run(
        Runtime(model="invalid-provider:no-model").call(summon.endpoints[0], carrier)
    )

    assert result == Result(value=1)
    assert len(received) == 1
    assert received[0] is canonical
    assert events == []


def test_agent_backed_path_checks_injected_values_before_application_code():
    starts = 0

    def apply(value: Annotated[int, Field(gt=10)], format: str) -> Result:
        nonlocal starts
        starts += 1
        return Result(value=value)

    operation = Operation(
        apply,
        bind={"value": FromRequest("value"), "format": AgentChoice()},
        output=Result,
    )
    summon = Summon("agent-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: BroadRequest, result=Required(operation, calls=Exactly(1))
    ) -> str:
        """Use an agent-owned format after validating the injected value."""
        ...

    def model(messages: Any, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("apply", {"format": "summary"})])

    with pytest.raises(_OperationInputError):
        asyncio.run(
            Runtime(model=FunctionModel(model), retries=0).call(
                summon.endpoints[0], {"value": 5}
            )
        )

    assert starts == 0


def test_agent_choice_pattern_uses_tool_schema_not_receiving_predicate():
    received: list[tuple[int, str]] = []

    def apply(value: int, format: Annotated[str, Field(pattern=r"^ok$")]) -> Result:
        received.append((value, format))
        return Result(value=value)

    operation = Operation(
        apply,
        bind={"value": FromRequest("value"), "format": AgentChoice()},
        output=Result,
    )
    summon = Summon("mixed-agent-choice-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: BroadRequest, result=Required(operation, calls=Exactly(1))
    ) -> str:
        """Validate agent-owned choices through the model-visible tool schema."""
        ...

    valid_turns = 0

    def valid_model(messages: Any, info: AgentInfo) -> ModelResponse:
        nonlocal valid_turns
        valid_turns += 1
        if valid_turns == 1:
            return ModelResponse(parts=[ToolCallPart("apply", {"format": "ok"})])
        return ModelResponse(parts=[TextPart('{"value":12}')])

    result = asyncio.run(
        Runtime(model=FunctionModel(valid_model), retries=0).call(
            summon.endpoints[0], {"value": 12}
        )
    )

    assert result == '{"value":12}'
    assert received == [(12, "ok")]

    def invalid_model(messages: Any, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("apply", {"format": "bad"})])

    with pytest.raises(UnexpectedModelBehavior, match="max retries"):
        asyncio.run(
            Runtime(model=FunctionModel(invalid_model), retries=0).call(
                summon.endpoints[0], {"value": 12}
            )
        )

    assert received == [(12, "ok")]


def test_receiving_failure_does_not_render_a_hostile_value():
    events: list[str] = []

    class Hostile:
        def __repr__(self) -> str:
            events.append("repr")
            raise AssertionError("repr must not run")

        def __str__(self) -> str:
            events.append("str")
            raise AssertionError("str must not run")

    def apply(value: int) -> Result:
        raise AssertionError("application code must not run")

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("hostile-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: AnyRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Reject hostile values without rendering them."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    hostile = Hostile()
    carrier = _validated_transport_request(
        plan, {"value": "<unavailable>"}, typed={"value": hostile}
    )
    with pytest.raises(_OperationInputError) as error:
        asyncio.run(
            Runtime(model="invalid-provider:no-model").call(
                summon.endpoints[0], carrier
            )
        )

    assert "Hostile" not in str(error.value)
    assert events == []


def test_receiving_literal_rejects_hostile_values_without_hash_or_equality():
    events: list[str] = []

    class Hostile:
        def __hash__(self) -> int:
            events.append("hash")
            raise AssertionError("hash must not run")

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            raise AssertionError("equality must not run")

        def __repr__(self) -> str:
            events.append("repr")
            raise AssertionError("repr must not run")

    def apply(value: Literal["allowed"]) -> Result:
        raise AssertionError("application code must not run")

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("literal-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: AnyRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Reject unsafe literal candidates without invoking their hooks."""
        ...

    plan = _registered_plan(summon.endpoints[0])
    assert plan is not None
    carrier = _validated_transport_request(
        plan, {"value": "<unavailable>"}, typed={"value": Hostile()}
    )
    with pytest.raises(_OperationInputError):
        asyncio.run(
            Runtime(model="invalid-provider:no-model").call(
                summon.endpoints[0], carrier
            )
        )

    assert events == []


def test_http_receiving_failure_is_stable_and_redacted():
    secret = 5

    def apply(value: Annotated[int, Field(gt=10)]) -> Result:
        raise AssertionError("application code must not run")

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("http-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: BroadRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Return a stable public receiving-contract failure."""
        ...

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/apply", json={"value": secret}
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request data did not satisfy a receiving operation contract."
    }
    assert str(secret) not in response.text


def test_http_explicitly_quoted_annotated_receiver_keeps_its_constraint():
    starts = 0

    def apply(value: "Annotated[int, Field(gt=10)]") -> Result:  # noqa: UP037
        nonlocal starts
        starts += 1
        return Result(value=value)

    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("quoted-receiving-contract")

    @summon("/apply")
    def endpoint(
        request: BroadRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Keep recursively resolved capability annotations executable."""
        ...

    client = TestClient(build_app(summon), raise_server_exceptions=False)
    rejected = client.post("/apply", json={"value": 5})
    accepted = client.post("/apply", json={"value": 11})

    assert rejected.status_code == 422
    assert accepted.status_code == 200
    assert accepted.json() == {"value": 11}
    assert starts == 1


def test_unresolved_quoted_receiver_annotation_fails_endpoint_registration():
    def apply(value: Any) -> Result:
        return Result(value=1)

    apply.__annotations__ = {"value": "MissingReceiverType", "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("unresolved-receiving-contract")

    with pytest.raises(TypeError, match=r"annotation.*could not be resolved"):

        @summon("/apply")
        def endpoint(
            request: AnyRequest, result=Required(operation, calls=Exactly(1))
        ) -> Result:
            """Never drop an unresolved receiving contract."""
            ...


def _receiver_service(annotation: Any, received: list[Any]) -> Summon:
    def apply(value: Any) -> Result:
        received.append(value)
        return Result(value=1)

    apply.__annotations__ = {"value": annotation, "return": Result}
    operation = Operation(apply, bind={"value": FromRequest("value")}, output=Result)
    summon = Summon("receiver-regressions")

    @summon("/apply")
    def endpoint(
        request: AnyRequest, result=Required(operation, calls=Exactly(1))
    ) -> Result:
        """Exercise the compiled receiving predicate."""
        ...

    return summon


def _call_with_canonical(summon: Summon, value: Any) -> Result:
    endpoint = summon.endpoints[0]
    plan = _registered_plan(endpoint)
    assert plan is not None
    carrier = _validated_transport_request(
        plan, {"value": "<unavailable>"}, typed={"value": value}
    )
    return asyncio.run(
        Runtime(model="invalid-provider:no-model").call(endpoint, carrier)
    )


@pytest.mark.parametrize(
    ("annotation", "value"),
    [(float, 1), (Literal[1], True)],
)
def test_receiver_requires_exact_primitive_and_literal_types(
    annotation: Any, value: Any
):
    received: list[Any] = []
    summon = _receiver_service(annotation, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, value)

    assert received == []


def test_receiver_rejects_a_mapping_for_a_model_parameter():
    class Payload(BaseModel):
        count: int

    received: list[Any] = []
    summon = _receiver_service(Payload, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, {"count": 1})

    assert received == []


def test_receiver_structurally_revalidates_constructed_model_instances():
    class Child(BaseModel):
        count: Annotated[int, Field(gt=0)]

    class Payload(BaseModel):
        child: Child

    invalid = Payload.model_construct(child=Child.model_construct(count=0))
    received: list[Any] = []
    summon = _receiver_service(Payload, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, invalid)

    valid = Payload(child=Child(count=1))
    assert _call_with_canonical(summon, valid) == Result(value=1)
    assert received == [valid]
    assert received[0] is valid


def test_receiver_model_config_constraints_apply_to_constructed_fields():
    class Payload(BaseModel):
        model_config = ConfigDict(str_max_length=2, allow_inf_nan=False)

        text: str
        number: float

    received: list[Any] = []
    summon = _receiver_service(Payload, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(
            summon, Payload.model_construct(text="too long", number=float("inf"))
        )

    valid = Payload(text="ok", number=1.0)
    assert _call_with_canonical(summon, valid) == Result(value=1)
    assert received == [valid]


def test_receiver_uses_narrow_model_config_for_a_broader_validated_subclass():
    class NarrowPayload(BaseModel):
        model_config = ConfigDict(str_max_length=2)

        text: str

    class BroadPayload(NarrowPayload):
        model_config = ConfigDict(str_max_length=20)

    received: list[Any] = []
    summon = _receiver_service(NarrowPayload, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, BroadPayload(text="too broad"))

    assert received == []


@pytest.mark.parametrize(
    "config",
    [
        ConfigDict(str_strip_whitespace=True),
        ConfigDict(str_to_lower=True),
        ConfigDict(str_to_upper=True),
        ConfigDict(coerce_numbers_to_str=True),
    ],
)
def test_transforming_receiver_model_config_is_rejected_at_registration(
    config: ConfigDict,
):
    class Payload(BaseModel):
        model_config = config

        text: str

    with pytest.raises(TypeError, match=r"transforming model config.*not hook-free"):
        _receiver_service(Payload, [])


def test_receiver_structurally_checks_typed_model_extras():
    class Payload(BaseModel):
        model_config = ConfigDict(extra="allow")

        __pydantic_extra__: dict[str, int] = Field(  # type: ignore[reportIncompatibleVariableOverride]
            init=False
        )
        count: int

    received: list[Any] = []
    summon = _receiver_service(Payload, received)
    invalid = Payload.model_construct(count=1, note="not-an-int")

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, invalid)

    valid = Payload.model_validate({"count": 1, "note": 2})
    assert _call_with_canonical(summon, valid) == Result(value=1)
    assert received == [valid]
    assert received[0] is valid


def test_model_storage_is_read_without_shadowed_descriptor_hooks():
    events: list[str] = []

    def hostile_dict(value: Any) -> dict[str, int]:
        events.append("dict")
        return {"count": 1}

    def hostile_extra(value: Any) -> dict[str, int]:
        events.append("extra")
        return {"note": 1}

    payload_type = type(
        "Payload",
        (BaseModel,),
        {
            "__annotations__": {
                "__pydantic_extra__": dict[str, int],
                "count": int,
            },
            "model_config": ConfigDict(extra="allow"),
            "__dict__": property(hostile_dict),
            "__pydantic_extra__": property(hostile_extra),
        },
    )
    invalid = object.__new__(payload_type)
    dict_descriptor = BaseModel.__dict__["__dict__"]
    extra_descriptor = BaseModel.__dict__["__pydantic_extra__"]
    type(dict_descriptor).__set__(dict_descriptor, invalid, {"count": "not-an-int"})
    type(extra_descriptor).__set__(extra_descriptor, invalid, {"note": "not-an-int"})
    received: list[Any] = []
    summon = _receiver_service(payload_type, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, invalid)

    assert received == []
    assert events == []


def test_model_storage_rejects_non_string_keys_without_equality_callbacks():
    events: list[str] = []

    class Payload(BaseModel):
        count: int

    class HostileKey:
        def __hash__(self) -> int:
            return hash("count")

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            return True

    invalid = Payload.model_construct(count=1)
    dict_descriptor = BaseModel.__dict__["__dict__"]
    storage = type(dict_descriptor).__get__(dict_descriptor, invalid, type(invalid))
    dict.clear(storage)
    storage[HostileKey()] = 1
    events.clear()
    received: list[Any] = []
    summon = _receiver_service(Payload, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, invalid)

    assert received == []
    assert events == []


@pytest.mark.parametrize(
    "metadata",
    [
        BeforeValidator(lambda value: value),
        AfterValidator(lambda value: value),
        WrapValidator(lambda value, handler: handler(value)),
        PlainValidator(lambda value: value),
    ],
)
def test_custom_functional_receiver_validators_are_rejected_at_registration(
    metadata: Any,
):
    with pytest.raises(TypeError, match="functional validator"):
        _receiver_service(Annotated[int, metadata], [])


def test_model_receiver_with_a_field_validator_is_rejected_at_registration():
    class Payload(BaseModel):
        count: int

        @field_validator("count")
        @classmethod
        def application_validator(cls, value: int) -> int:
            return value

    with pytest.raises(TypeError, match="functional validator"):
        _receiver_service(Payload, [])


def test_unsupported_builtin_constraint_is_rejected_instead_of_dropped():
    constrained = Annotated[Decimal, Field(max_digits=4, decimal_places=2)]

    with pytest.raises(TypeError, match=r"constraints.*not supported"):
        _receiver_service(constrained, [])


def test_string_pattern_receiver_is_rejected_at_endpoint_registration():
    annotation = Annotated[str, Field(pattern=r"^a$")]

    assert re.search(r"^a$", "a\n") is not None
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python("a\n")
    with pytest.raises(TypeError, match=r"string pattern.*not supported"):
        _receiver_service(annotation, [])


def test_non_pattern_string_constraints_remain_supported():
    annotation = Annotated[str, Field(min_length=2, max_length=4)]
    received: list[Any] = []
    summon = _receiver_service(annotation, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, "a")

    assert _call_with_canonical(summon, "safe") == Result(value=1)
    assert received == ["safe"]


def test_float_multiple_of_receiver_is_rejected_at_endpoint_registration():
    with pytest.raises(TypeError, match=r"float.*multiple_of.*not supported"):
        _receiver_service(Annotated[float, Field(multiple_of=1)], [])


@pytest.mark.parametrize(
    "annotation",
    [
        Decimal,
        Annotated[Decimal, Field(gt=Decimal("-10"))],
        Annotated[Decimal, MultipleOf(Decimal("0.1"))],
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_decimal_receiver_rejects_non_finite_values_before_constraints(
    annotation: Any, value: Decimal
):
    received: list[Any] = []
    summon = _receiver_service(annotation, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, value)

    assert received == []


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1.25"), Decimal("1E+1000")])
def test_bare_decimal_receiver_accepts_finite_values(value: Decimal):
    received: list[Any] = []
    summon = _receiver_service(Decimal, received)

    assert _call_with_canonical(summon, value) == Result(value=1)
    assert received == [value]


def test_decimal_explicit_finite_constraint_accepts_large_finite_value():
    value = Decimal("1E+1000")
    received: list[Any] = []
    summon = _receiver_service(Annotated[Decimal, Field(allow_inf_nan=False)], received)

    assert _call_with_canonical(summon, value) == Result(value=1)
    assert received == [value]


def test_decimal_allow_inf_nan_receiver_is_rejected_at_registration():
    annotation = Annotated[Decimal, Field(allow_inf_nan=True)]

    with pytest.raises(TypeError, match=r"Decimal.*allow_inf_nan.*not supported"):
        _receiver_service(annotation, [])


@pytest.mark.parametrize(
    ("annotation", "invalid", "valid"),
    [
        (Annotated[int, Field(multiple_of=2)], 3, 4),
        (
            Annotated[Decimal, MultipleOf(Decimal("0.1"))],
            Decimal("1.25"),
            Decimal("1.2"),
        ),
    ],
)
def test_integer_and_decimal_multiple_of_receivers_remain_supported(
    annotation: Any, invalid: Any, valid: Any
):
    received: list[Any] = []
    summon = _receiver_service(annotation, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, invalid)

    assert _call_with_canonical(summon, valid) == Result(value=1)
    assert received == [valid]


def test_enum_receiver_is_rejected_at_endpoint_registration():
    class Choice(Enum):
        ALLOWED = "allowed"

    with pytest.raises(TypeError, match=r"enum.*not supported"):
        _receiver_service(Choice, [])


def test_set_and_dict_validation_do_not_rehash_canonical_members():
    events: list[str] = []

    class Key:
        @classmethod
        def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
            return core_schema.is_instance_schema(cls)

        def __hash__(self) -> int:
            events.append("hash")
            return object.__hash__(self)

    item = Key()
    canonical_set = {item}
    canonical_dict = {item: 1}
    events.clear()

    set_received: list[Any] = []
    dict_received: list[Any] = []
    assert _call_with_canonical(
        _receiver_service(set[Key], set_received), canonical_set
    ) == Result(value=1)
    assert _call_with_canonical(
        _receiver_service(dict[Key, int], dict_received), canonical_dict
    ) == Result(value=1)

    assert set_received[0] is canonical_set
    assert dict_received[0] is canonical_dict
    assert events == []


def test_union_accepts_the_first_safely_matching_branch():
    events: list[str] = []

    class Payload:
        @classmethod
        def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
            return core_schema.is_instance_schema(cls)

        def __hash__(self) -> int:
            events.append("hash")
            raise AssertionError("hash must not run")

        def __eq__(self, other: object) -> bool:
            events.append("eq")
            raise AssertionError("equality must not run")

    canonical = Payload()
    received: list[Any] = []
    summon = _receiver_service(Literal["other"] | Payload, received)

    assert _call_with_canonical(summon, canonical) == Result(value=1)
    assert received[0] is canonical
    assert events == []


def test_callable_discriminator_receiver_is_rejected_at_registration():
    class Cat(BaseModel):
        name: str

    class Dog(BaseModel):
        name: str

    discriminator_calls = 0

    def choose_branch(value: Any) -> str:
        nonlocal discriminator_calls
        discriminator_calls += 1
        return "cat"

    annotation = Annotated[
        Annotated[Cat, Tag("cat")] | Annotated[Dog, Tag("dog")],
        Discriminator(choose_branch),
    ]

    with pytest.raises(TypeError, match=r"callable discriminator.*not hook-free"):
        _receiver_service(annotation, [])

    assert discriminator_calls == 0


def test_string_discriminator_tagged_union_receiver_remains_supported():
    class Cat(BaseModel):
        kind: Literal["cat"]
        lives: int

    class Dog(BaseModel):
        kind: Literal["dog"]
        breed: str

    annotation = Annotated[Cat | Dog, Field(discriminator="kind")]
    received: list[Any] = []
    summon = _receiver_service(annotation, received)
    canonical = Cat(kind="cat", lives=9)

    assert _call_with_canonical(summon, canonical) == Result(value=1)
    assert received == [canonical]
    assert received[0] is canonical


def test_failed_union_branch_cannot_authorize_a_later_branch_via_seen_state():
    class Payload(BaseModel):
        count: int

    invalid = Payload.model_construct(count="not-an-int")
    received: list[Any] = []
    annotation = tuple[Payload, int] | tuple[Payload, str]
    summon = _receiver_service(annotation, received)

    with pytest.raises(_OperationInputError):
        _call_with_canonical(summon, (invalid, "matches-second-tail"))

    assert received == []


def test_list_subclass_is_inspected_without_override_hooks_and_preserved():
    events: list[str] = []

    class CanonicalList(list[int]):
        def __iter__(self):
            events.append("iter")
            raise AssertionError("override must not run")

        def __len__(self) -> int:
            events.append("len")
            raise AssertionError("override must not run")

        def __getitem__(self, index: Any) -> Any:
            events.append("getitem")
            raise AssertionError("override must not run")

    canonical = CanonicalList([1, 2])
    received: list[Any] = []
    summon = _receiver_service(
        Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=2)],
        received,
    )

    assert _call_with_canonical(summon, canonical) == Result(value=1)
    assert received[0] is canonical
    assert events == []
