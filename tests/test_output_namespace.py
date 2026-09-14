"""Output models must have one unambiguous emitted JSON namespace."""

import asyncio
from typing import Any

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


class DuplicateFieldOutput(BaseModel):
    first: int = Field(serialization_alias="value")
    value: int


class DuplicateAliasOutput(BaseModel):
    first: int = Field(alias="value")
    value: int


class SafeAliasesOutput(BaseModel):
    first: int = Field(validation_alias="inputValue", serialization_alias="firstValue")
    value: int


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


@dataclass
class DataclassCollisionOutput:
    first: int = Field(serialization_alias="value")
    value: int = 0


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


def _direct_summon(output: type[BaseModel], result: BaseModel) -> Summon:
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


def test_http_emits_each_safe_output_key_once():
    output = _set_extra(AliasedExtraOutput(value=7), note="safe")
    response = TestClient(build_app(_direct_summon(AliasedExtraOutput, output))).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 200
    assert response.json() == {"wireValue": 7, "note": "safe"}
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
