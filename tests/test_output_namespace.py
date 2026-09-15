"""Output models must have one unambiguous emitted JSON namespace."""

import asyncio
from dataclasses import InitVar
from typing import Annotated, Any

import pytest
from fastapi.testclient import TestClient
from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    TypeAdapter,
    ValidationError,
    computed_field,
    model_serializer,
    model_validator,
)
from pydantic.dataclasses import dataclass
from typing_extensions import TypedDict

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._output_validation import _compile_output_validator
from summonpot.runtime import Runtime, _OperationOutputError
from summonpot.server import build_app


class Request(BaseModel):
    value: int


class AliasedExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")


class AfterValidatorExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")

    @model_validator(mode="after")
    def add_extra(self) -> "AfterValidatorExtraOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__["wireValue"] = 99
        return self


class WrapValidatorExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")

    @model_validator(mode="wrap")
    @classmethod
    def add_extra(cls, value: Any, handler: Any) -> "WrapValidatorExtraOutput":
        result = handler(value)
        assert result.__pydantic_extra__ is not None
        result.__pydantic_extra__["wireValue"] = 99
        return result


class ValidatorSafeExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")

    @model_validator(mode="after")
    def add_after_extra(self) -> "ValidatorSafeExtraOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__["afterNote"] = "safe"
        return self

    @model_validator(mode="wrap")
    @classmethod
    def add_wrap_extra(cls, value: Any, handler: Any) -> "ValidatorSafeExtraOutput":
        result = handler(value)
        assert result.__pydantic_extra__ is not None
        result.__pydantic_extra__["wrapNote"] = "safe"
        return result


class EmptyAliasAfterValidatorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="")

    @model_validator(mode="after")
    def add_empty_alias_extra(self) -> "EmptyAliasAfterValidatorOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__[""] = "hostile"
        return self


class EmptyAliasWrapValidatorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="")

    @model_validator(mode="wrap")
    @classmethod
    def add_empty_alias_extra(
        cls, value: Any, handler: Any
    ) -> "EmptyAliasWrapValidatorOutput":
        result = handler(value)
        assert result.__pydantic_extra__ is not None
        result.__pydantic_extra__[""] = "hostile"
        return result


class EmptyAliasSafeExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="")

    @model_validator(mode="after")
    def add_safe_extra(self) -> "EmptyAliasSafeExtraOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__["note"] = "safe"
        return self


EMPTY_ALIAS_HOOKS: list[str] = []


class EmptyAliasHostileOutput(EmptyAliasAfterValidatorOutput):
    @model_serializer(mode="wrap")
    def serialize(self, handler: Any) -> Any:
        EMPTY_ALIAS_HOOKS.append("serializer")
        return handler(self)

    def __copy__(self):
        EMPTY_ALIAS_HOOKS.append("copy")
        raise AssertionError("copy hook called during output validation")

    def __deepcopy__(self, memo: Any = None):
        EMPTY_ALIAS_HOOKS.append("deepcopy")
        raise AssertionError("deepcopy hook called during output validation")

    def __repr__(self) -> str:
        EMPTY_ALIAS_HOOKS.append("repr")
        raise AssertionError("repr hook called during output validation")

    def __str__(self) -> str:
        EMPTY_ALIAS_HOOKS.append("str")
        raise AssertionError("str hook called during output validation")


class DuplicateFieldOutput(BaseModel):
    first: int = Field(serialization_alias="value")
    value: int


class DuplicateAliasOutput(BaseModel):
    first: int = Field(alias="value")
    value: int


class SerializerCollisionOutput(BaseModel):
    value: int

    @model_serializer
    def serialize(self) -> DuplicateFieldOutput:
        return DuplicateFieldOutput.model_construct(first=self.value, value=self.value)


class SafeAliasesOutput(BaseModel):
    first: int = Field(validation_alias="inputValue", serialization_alias="firstValue")
    value: int


class SerializerSafeOutput(BaseModel):
    value: int

    @model_serializer
    def serialize(self) -> SafeAliasesOutput:
        return SafeAliasesOutput.model_validate(
            {"inputValue": self.value, "value": self.value}
        )


class ComputedCollisionOutput(BaseModel):
    value: int

    @computed_field(alias="value")
    @property
    def doubled(self) -> int:
        return self.value * 2


class ComputedExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int

    @computed_field(alias="wireComputed")
    @property
    def doubled(self) -> int:
        return self.value * 2


class EmptyComputedAliasAfterValidatorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int

    @computed_field(alias="")
    @property
    def doubled(self) -> int:
        return self.value * 2

    @model_validator(mode="after")
    def add_empty_alias_extra(self) -> "EmptyComputedAliasAfterValidatorOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__[""] = "hostile"
        return self


@dataclass
class DataclassCollisionOutput:
    first: int = Field(serialization_alias="value")
    value: int = 0


@dataclass
class InitVarSerializationAliasOutput:
    init_value: InitVar[int] = Field(serialization_alias="value")
    value: int = 0


@dataclass
class InitVarValidationCollisionOutput:
    init_value: InitVar[int] = Field(
        validation_alias="value", serialization_alias="initValue"
    )
    value: int = 0


class NestedInitVarOutput(BaseModel):
    item: InitVarSerializationAliasOutput


@dataclass
class NestedDataclassCarrier:
    item: AliasedExtraOutput

    @model_validator(mode="after")
    def add_nested_collision(self) -> "NestedDataclassCarrier":
        assert self.item.__pydantic_extra__ is not None
        self.item.__pydantic_extra__["wireValue"] = "hostile"
        return self


@dataclass
class SafeNestedDataclassCarrier:
    item: AliasedExtraOutput

    @model_validator(mode="after")
    def add_nested_extra(self) -> "SafeNestedDataclassCarrier":
        assert self.item.__pydantic_extra__ is not None
        self.item.__pydantic_extra__["note"] = "safe"
        return self


@dataclass
class EmptyAliasNestedDataclassCarrier:
    item: EmptyAliasAfterValidatorOutput


class EmptyAliasNestedDataclassEnvelope(BaseModel):
    payload: EmptyAliasNestedDataclassCarrier


class EmptyAliasRootDataclassEnvelope(BaseModel):
    payload: RootModel[EmptyAliasNestedDataclassCarrier]


class EmptyAliasUnionDataclassEnvelope(BaseModel):
    payload: EmptyAliasNestedDataclassCarrier | int


class NestedDataclassEnvelope(BaseModel):
    payload: NestedDataclassCarrier


class RootDataclassEnvelope(BaseModel):
    payload: RootModel[NestedDataclassCarrier]


class UnionDataclassEnvelope(BaseModel):
    payload: NestedDataclassCarrier | int


class SafeNestedDataclassEnvelope(BaseModel):
    payload: SafeNestedDataclassCarrier


class TypedDictCollisionOutput(TypedDict):
    first: int
    value: int


TypedDictCollisionOutput.__pydantic_config__ = ConfigDict(  # type: ignore[attr-defined]
    alias_generator=lambda name: "value" if name == "first" else name
)


HOOKS: list[str] = []


class HostileCollisionOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")

    @model_serializer
    def serialize(self) -> dict[str, int]:
        HOOKS.append("serializer")
        raise AssertionError("serializer called during output validation")

    def __copy__(self):
        HOOKS.append("copy")
        raise AssertionError("copy hook called during output validation")

    def __deepcopy__(self, memo: Any = None):
        HOOKS.append("deepcopy")
        raise AssertionError("deepcopy hook called during output validation")

    def __repr__(self) -> str:
        HOOKS.append("repr")
        raise AssertionError("repr hook called during output validation")

    def __str__(self) -> str:
        HOOKS.append("str")
        raise AssertionError("str hook called during output validation")


def _set_extra(model: BaseModel, **extras: Any) -> BaseModel:
    object.__setattr__(model, "__pydantic_extra__", extras)
    return model


def _direct_summon(output: Any, result: Any) -> Summon:
    def operation(value: int) -> output:  # type: ignore[valid-type]
        return result

    summon = Summon("output-namespace")

    @summon("/output")
    def endpoint(
        request: Request,
        response=Required(
            Operation(operation, bind={"value": FromRequest("value")}, output=output),
            calls=Exactly(1),
        ),
    ) -> output:  # type: ignore[valid-type]
        """Return a namespace-safe output."""
        ...

    return summon


def test_extra_cannot_shadow_a_declared_serialization_alias():
    output = _set_extra(AliasedExtraOutput(value=7), wireValue="hostile")

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(AliasedExtraOutput)).validate_python(
            output
        )


def test_extra_cannot_shadow_a_computed_field_alias():
    output = _set_extra(ComputedExtraOutput(value=7), wireComputed="hostile")

    with pytest.raises(ValidationError, match="wireComputed"):
        _compile_output_validator(TypeAdapter(ComputedExtraOutput)).validate_python(
            output
        )


@pytest.mark.parametrize(
    "output",
    [AfterValidatorExtraOutput, WrapValidatorExtraOutput],
)
def test_model_validators_cannot_add_colliding_extras_after_fields_join(output: Any):
    result = output.model_construct(value=7)

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(result)


def test_model_validators_can_add_noncolliding_extras_after_fields_join():
    result = ValidatorSafeExtraOutput.model_construct(value=7)

    validated = _compile_output_validator(
        TypeAdapter(ValidatorSafeExtraOutput)
    ).validate_python(result)

    assert validated.model_dump(mode="json", by_alias=True) == {
        "wireValue": 7,
        "afterNote": "safe",
        "wrapNote": "safe",
    }


@pytest.mark.parametrize(
    "output,value",
    [
        (EmptyAliasAfterValidatorOutput, {"value": 7}),
        (EmptyAliasWrapValidatorOutput, {"value": 7}),
        (EmptyComputedAliasAfterValidatorOutput, {"value": 7}),
        (RootModel[EmptyAliasAfterValidatorOutput], {"value": 7}),
        (EmptyAliasWrapValidatorOutput | int, {"value": 7}),
        (EmptyAliasNestedDataclassCarrier, {"item": {"value": 7}}),
    ],
)
def test_post_validation_extra_cannot_shadow_an_empty_serialization_alias(
    output: Any, value: Any
):
    with pytest.raises(ValidationError, match=r"shadow.*''"):
        _compile_output_validator(TypeAdapter(output)).validate_python(value)


def test_post_validation_noncolliding_extra_preserves_empty_serialization_alias():
    validated = _compile_output_validator(
        TypeAdapter(EmptyAliasSafeExtraOutput)
    ).validate_python({"value": 7})

    assert validated.model_dump(mode="json", by_alias=True) == {"": 7, "note": "safe"}


def test_noncolliding_extra_preserves_alias_serialization():
    output = _set_extra(AliasedExtraOutput(value=7), note="safe")

    validated = _compile_output_validator(
        TypeAdapter(AliasedExtraOutput)
    ).validate_python(output)

    assert validated.model_dump(mode="json", by_alias=True) == {
        "wireValue": 7,
        "note": "safe",
    }


@pytest.mark.parametrize(
    "output",
    [
        DuplicateFieldOutput,
        DuplicateAliasOutput,
        list[DuplicateFieldOutput],
        DuplicateFieldOutput | int,
        RootModel[DuplicateFieldOutput],
    ],
)
def test_duplicate_declared_serialization_aliases_are_rejected(output: Any):
    with pytest.raises(TypeError, match=r"duplicate JSON key 'value'"):
        _compile_output_validator(TypeAdapter(output))


def test_duplicate_declared_keys_fail_during_endpoint_registration():
    result = DuplicateFieldOutput.model_construct(first=1, value=2)

    with pytest.raises(TypeError, match="duplicate JSON key 'value'"):
        _direct_summon(DuplicateFieldOutput, result)


def test_declared_serializer_return_schema_rejects_duplicate_emitted_keys():
    with pytest.raises(TypeError, match="duplicate JSON key 'value'"):
        _compile_output_validator(TypeAdapter(SerializerCollisionOutput))


def test_declared_serializer_return_schema_with_distinct_keys_remains_supported():
    _compile_output_validator(TypeAdapter(SerializerSafeOutput))


def test_distinct_validation_and_serialization_aliases_remain_supported():
    validated = _compile_output_validator(
        TypeAdapter(SafeAliasesOutput)
    ).validate_python({"inputValue": 3, "value": 4})

    assert validated.model_dump(mode="json", by_alias=True) == {
        "firstValue": 3,
        "value": 4,
    }


@pytest.mark.parametrize(
    "output",
    [ComputedCollisionOutput, DataclassCollisionOutput, TypedDictCollisionOutput],
)
def test_other_object_shaped_outputs_reject_duplicate_emitted_keys(output: Any):
    with pytest.raises(TypeError, match="duplicate JSON key 'value'"):
        _compile_output_validator(TypeAdapter(output))


def test_dataclass_init_var_is_excluded_from_the_emitted_namespace():
    validator = _compile_output_validator(TypeAdapter(NestedInitVarOutput))

    validated = validator.validate_python({"item": {"init_value": 3, "value": 7}})

    assert validated.model_dump(mode="json", by_alias=True) == {"item": {"value": 7}}


def test_dataclass_init_var_remains_in_the_validation_namespace():
    with pytest.raises(TypeError, match=r"validation.*key 'value'"):
        _compile_output_validator(TypeAdapter(InitVarValidationCollisionOutput))


@pytest.mark.parametrize(
    "output,value",
    [
        (NestedDataclassCarrier, {"item": {"value": 7}}),
        (RootModel[NestedDataclassCarrier], {"item": {"value": 7}}),
        (NestedDataclassCarrier | int, {"item": {"value": 7}}),
    ],
)
def test_dataclass_carrier_cannot_hide_nested_post_validation_collision(
    output: Any, value: Any
):
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(value)


def test_dataclass_carrier_preserves_nested_noncolliding_post_validation_extra():
    validator = _compile_output_validator(TypeAdapter(SafeNestedDataclassCarrier))

    validated = validator.validate_python({"item": {"value": 7}})

    assert TypeAdapter(SafeNestedDataclassCarrier).dump_python(
        validated, mode="json", by_alias=True
    ) == {"item": {"wireValue": 7, "note": "safe"}}


def test_root_scalar_output_remains_supported():
    output = RootModel[int](7)

    assert (
        _compile_output_validator(TypeAdapter(type(output))).validate_python(output)
        == output
    )


def test_collision_validation_does_not_call_application_object_hooks():
    HOOKS.clear()
    output = _set_extra(HostileCollisionOutput(value=7), wireValue="hostile")

    with pytest.raises(ValidationError):
        _compile_output_validator(TypeAdapter(HostileCollisionOutput)).validate_python(
            output
        )

    assert HOOKS == []


def test_empty_alias_collision_rejection_does_not_call_application_object_hooks():
    EMPTY_ALIAS_HOOKS.clear()
    output = EmptyAliasHostileOutput.model_construct(value=7)

    with pytest.raises(ValidationError):
        _compile_output_validator(TypeAdapter(EmptyAliasHostileOutput)).validate_python(
            output
        )

    assert EMPTY_ALIAS_HOOKS == []


def test_http_rejects_colliding_extra_before_response_serialization():
    output = _set_extra(AliasedExtraOutput(value=7), wireValue="hostile")
    summon = _direct_summon(AliasedExtraOutput, output)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert "hostile" not in response.text


@pytest.mark.parametrize(
    "output,result",
    [
        (EmptyAliasAfterValidatorOutput, {"value": 7}),
        (EmptyAliasWrapValidatorOutput, {"value": 7}),
        (EmptyComputedAliasAfterValidatorOutput, {"value": 7}),
        (RootModel[EmptyAliasAfterValidatorOutput], {"value": 7}),
        (
            EmptyAliasNestedDataclassEnvelope,
            {"payload": {"item": {"value": 7}}},
        ),
        (
            EmptyAliasRootDataclassEnvelope,
            {"payload": {"item": {"value": 7}}},
        ),
        (
            EmptyAliasUnionDataclassEnvelope,
            {"payload": {"item": {"value": 7}}},
        ),
    ],
)
def test_http_rejects_post_validation_empty_alias_collision(output: Any, result: Any):
    summon = _direct_summon(output, result)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert "hostile" not in response.text


def test_http_empty_alias_collision_rejection_does_not_call_object_hooks():
    EMPTY_ALIAS_HOOKS.clear()
    output = EmptyAliasHostileOutput.model_construct(value=7)
    summon = _direct_summon(EmptyAliasHostileOutput, output)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )
    assert EMPTY_ALIAS_HOOKS == []

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert EMPTY_ALIAS_HOOKS == []


def test_http_preserves_valid_empty_serialization_alias():
    response = TestClient(
        build_app(_direct_summon(EmptyAliasSafeExtraOutput, {"value": 7}))
    ).post("/output", json={"value": 7})

    assert response.status_code == 200
    assert response.json() == {"": 7, "note": "safe"}
    assert response.text.count('""') == 1
    assert response.text.count('"note"') == 1


def test_http_emits_each_safe_output_key_once():
    output = _set_extra(AliasedExtraOutput(value=7), note="safe")
    response = TestClient(build_app(_direct_summon(AliasedExtraOutput, output))).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 200
    assert response.json() == {"wireValue": 7, "note": "safe"}
    assert response.text.count('"wireValue"') == 1
    assert response.text.count('"note"') == 1


@pytest.mark.parametrize(
    "output,result",
    [
        (NestedDataclassEnvelope, {"payload": {"item": {"value": 7}}}),
        (RootDataclassEnvelope, {"payload": {"item": {"value": 7}}}),
        (UnionDataclassEnvelope, {"payload": {"item": {"value": 7}}}),
    ],
)
def test_http_rejects_nested_dataclass_post_validation_collision(
    output: Any, result: Any
):
    summon = _direct_summon(output, result)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    response = TestClient(
        build_app(summon),
        raise_server_exceptions=False,
    ).post("/output", json={"value": 7})

    assert response.status_code == 500
    assert "hostile" not in response.text


def test_http_emits_nested_dataclass_noncolliding_extra_once():
    response = TestClient(
        build_app(
            _direct_summon(
                SafeNestedDataclassEnvelope,
                {"payload": {"item": {"value": 7}}},
            )
        )
    ).post("/output", json={"value": 7})

    assert response.status_code == 200
    assert response.json() == {"payload": {"item": {"wireValue": 7, "note": "safe"}}}
    assert response.text.count('"wireValue"') == 1
    assert response.text.count('"note"') == 1


class SeparateNamespaceCollisionOutput(BaseModel):
    first: int = Field(alias="value", serialization_alias="firstValue")
    value: int


class SingleSegmentAliasPathCollisionOutput(BaseModel):
    first: int = Field(
        validation_alias=AliasPath("value"), serialization_alias="firstValue"
    )
    value: int


class NestedAliasPathOutput(BaseModel):
    first: int = Field(
        validation_alias=AliasPath("payload", "value"),
        serialization_alias="firstValue",
    )
    value: int


class NameOnlyAliasOutput(BaseModel):
    model_config = ConfigDict(validate_by_alias=False, validate_by_name=True)
    first: int = Field(alias="value", serialization_alias="firstValue")
    value: int


class AliasAndNameOutput(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)
    first: int = Field(alias="value", serialization_alias="firstValue")
    value: int


class NestedAliasedExtraOutput(BaseModel):
    item: AliasedExtraOutput


class AllowedExtraTypedDict(TypedDict):
    value: Annotated[int, Field(serialization_alias="wireValue")]


AllowedExtraTypedDict.__pydantic_config__ = ConfigDict(  # type: ignore[attr-defined]
    extra="allow"
)


class NestedAllowedExtraTypedDictOutput(BaseModel):
    item: AllowedExtraTypedDict


def test_mapping_extra_cannot_shadow_a_declared_serialization_alias():
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(AliasedExtraOutput)).validate_python(
            {"value": 7, "wireValue": "hostile"}
        )


def test_nested_mapping_extra_cannot_shadow_a_declared_serialization_alias():
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(NestedAliasedExtraOutput)
        ).validate_python({"item": {"value": 7, "wireValue": "hostile"}})


def test_nested_typed_dict_extra_cannot_shadow_a_serialization_alias():
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(NestedAllowedExtraTypedDictOutput)
        ).validate_python({"item": {"value": 7, "wireValue": 99}})


def test_nested_typed_dict_noncolliding_extra_remains_supported():
    validated = _compile_output_validator(
        TypeAdapter(NestedAllowedExtraTypedDictOutput)
    ).validate_python({"item": {"value": 7, "note": "safe"}})

    assert validated.model_dump(mode="json", by_alias=True) == {
        "item": {"wireValue": 7, "note": "safe"}
    }


def test_mapping_and_nested_mapping_noncolliding_extras_remain_supported():
    validator = _compile_output_validator(TypeAdapter(NestedAliasedExtraOutput))

    validated = validator.validate_python({"item": {"value": 7, "note": "safe"}})

    assert validated.model_dump(mode="json", by_alias=True) == {
        "item": {"wireValue": 7, "note": "safe"}
    }


def test_validation_alias_namespace_is_checked_separately_from_serialization():
    with pytest.raises(TypeError, match=r"validation.*key 'value'"):
        _compile_output_validator(TypeAdapter(SeparateNamespaceCollisionOutput))


def test_single_segment_alias_path_collision_fails_during_endpoint_registration():
    summon = Summon("output-namespace")

    with pytest.raises(TypeError, match=r"validation.*key 'value'"):

        @summon("/output")
        def endpoint(request: Request) -> SingleSegmentAliasPathCollisionOutput:
            """Reject a direct AliasPath collision."""
            ...

    assert summon.endpoints == []


def test_nested_alias_path_with_distinct_direct_key_registers():
    summon = Summon("output-namespace")

    @summon("/output")
    def endpoint(request: Request) -> NestedAliasPathOutput:
        """Accept a nested AliasPath without a direct-key collision."""
        ...

    assert len(summon.endpoints) == 1


def test_disabled_alias_validation_does_not_create_registration_collision():
    summon = Summon("output-namespace")

    @summon("/output")
    def endpoint(request: Request) -> NameOnlyAliasOutput:
        """Accept distinct field names when validation aliases are disabled."""
        ...

    assert len(summon.endpoints) == 1


def test_enabled_alias_validation_creates_registration_collision():
    summon = Summon("output-namespace")

    with pytest.raises(TypeError, match=r"validation.*key 'value'"):

        @summon("/output")
        def endpoint(request: Request) -> AliasAndNameOutput:
            """Reject an enabled validation-alias collision."""
            ...

    assert summon.endpoints == []


def test_distinct_input_and_output_namespaces_preserve_both_fields():
    validated = _compile_output_validator(
        TypeAdapter(SafeAliasesOutput)
    ).validate_python({"inputValue": 7, "value": 3})

    assert validated.first == 7
    assert validated.value == 3


def test_plain_endpoint_response_namespace_is_checked_at_registration():
    summon = Summon("output-namespace")

    with pytest.raises(TypeError, match="duplicate JSON key 'value'"):

        @summon("/output")
        def endpoint(request: Request) -> DuplicateFieldOutput:
            """Reject an ambiguous endpoint response."""
            ...

    assert summon.endpoints == []


def test_plain_endpoint_with_safe_response_namespace_registers():
    summon = Summon("output-namespace")

    @summon("/output")
    def endpoint(request: Request) -> SafeAliasesOutput:
        """Accept an unambiguous endpoint response."""
        ...

    assert len(summon.endpoints) == 1


def test_unsupported_operation_shape_namespace_is_checked_at_registration():
    def operation(value: int) -> DuplicateFieldOutput:
        return DuplicateFieldOutput.model_construct(first=value, value=value)

    summon = Summon("output-namespace")

    with pytest.raises(TypeError, match="duplicate JSON key 'value'"):

        @summon("/output")
        def endpoint(
            request: Request,
            response=Required(
                Operation(
                    operation,
                    bind={"value": FromRequest("value")},
                    output=DuplicateFieldOutput,
                ),
                calls=Exactly(2),
            ),
        ) -> SafeAliasesOutput:
            """Reject an ambiguous output on an unsupported operation shape."""
            ...

    assert summon.endpoints == []


def test_every_operation_output_namespace_is_checked_at_registration():
    def first(value: int) -> SafeAliasesOutput:
        return SafeAliasesOutput.model_validate({"inputValue": value, "value": value})

    def second(value: int) -> DuplicateFieldOutput:
        return DuplicateFieldOutput.model_construct(first=value, value=value)

    summon = Summon("output-namespace")

    with pytest.raises(TypeError, match="duplicate JSON key 'value'"):

        @summon("/output")
        def endpoint(
            request: Request,
            one=Required(
                Operation(
                    first,
                    bind={"value": FromRequest("value")},
                    output=SafeAliasesOutput,
                ),
                calls=Exactly(1),
            ),
            two=Required(
                Operation(
                    second,
                    bind={"value": FromRequest("value")},
                    output=DuplicateFieldOutput,
                ),
                calls=Exactly(1),
            ),
        ) -> SafeAliasesOutput:
            """Reject an ambiguous output from any declared operation."""
            ...

    assert summon.endpoints == []


def test_unsupported_and_multi_operation_safe_namespaces_register():
    def first_operation(value: int) -> SafeAliasesOutput:
        return SafeAliasesOutput.model_validate({"inputValue": value, "value": value})

    first_contract = Operation(
        first_operation,
        bind={"value": FromRequest("value")},
        output=SafeAliasesOutput,
    )

    def second_operation(value: int) -> SafeAliasesOutput:
        return SafeAliasesOutput.model_validate({"inputValue": value, "value": value})

    second_contract = Operation(
        second_operation,
        bind={"value": FromRequest("value")},
        output=SafeAliasesOutput,
    )
    summon = Summon("output-namespace")

    @summon("/output")
    def endpoint(
        request: Request,
        one=Required(first_contract, calls=Exactly(2)),
        two=Required(second_contract, calls=Exactly(1)),
    ) -> SafeAliasesOutput:
        """Accept safe namespaces without widening runtime support."""
        ...

    assert len(summon.endpoints) == 1
