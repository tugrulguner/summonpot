"""Output models must have one unambiguous emitted JSON namespace."""

import asyncio
import math
from collections import deque
from dataclasses import InitVar
from types import GetSetDescriptorType, MemberDescriptorType
from typing import Annotated, Any, Literal, SupportsIndex, get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    AliasPath,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    RootModel,
    Tag,
    TypeAdapter,
    ValidationError,
    computed_field,
    model_serializer,
    model_validator,
)
from pydantic.dataclasses import dataclass
from pydantic_ai.models.test import TestModel
from typing_extensions import TypedDict

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._output_validation import _compile_output_validator
from summonpot.runtime import Runtime, _OperationOutputError
from summonpot.server import build_app

CALLABLE_DISCRIMINATOR_CALLS: list[str] = []


def callable_output_discriminator(value: Any) -> str:
    CALLABLE_DISCRIMINATOR_CALLS.append("called")
    return "safe"


class CallableDiscriminatorSafe(BaseModel):
    value: int


class CallableDiscriminatorOther(BaseModel):
    value: str


CallableDiscriminatorOutput = Annotated[
    Annotated[CallableDiscriminatorSafe, Tag("safe")]
    | Annotated[CallableDiscriminatorOther, Tag("other")],
    Discriminator(callable_output_discriminator),
]


@pytest.mark.parametrize(
    "output",
    [CallableDiscriminatorOutput, list[CallableDiscriminatorOutput]],
)
def test_callable_output_discriminator_is_rejected_without_invocation(output: Any):
    CALLABLE_DISCRIMINATOR_CALLS.clear()

    with pytest.raises(TypeError, match="Callable discriminators are unsupported"):
        _compile_output_validator(TypeAdapter(output))

    assert CALLABLE_DISCRIMINATOR_CALLS == []


def test_callable_output_discriminator_fails_during_endpoint_registration():
    CALLABLE_DISCRIMINATOR_CALLS.clear()

    with pytest.raises(TypeError, match="Callable discriminators are unsupported"):
        _direct_summon(
            CallableDiscriminatorOutput,
            CallableDiscriminatorSafe(value=7),
        )

    assert CALLABLE_DISCRIMINATOR_CALLS == []


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


DATACLASS_SUBCLASS_HOOKS: list[str] = []


@dataclass(slots=True)
class SlottedNestedDataclassCarrier:
    item: AliasedExtraOutput


class ShadowingSlottedDataclassCarrier(SlottedNestedDataclassCarrier):
    __slots__ = ()

    @property
    def __dict__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any]:
        DATACLASS_SUBCLASS_HOOKS.append("dict")
        raise AssertionError("__dict__ hook called during output audit")

    def __repr__(self) -> str:
        DATACLASS_SUBCLASS_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")


class ReplacingDataclassSubclassEnvelope(BaseModel):
    payload: SlottedNestedDataclassCarrier

    @model_validator(mode="after")
    def replace_with_subclass(self) -> "ReplacingDataclassSubclassEnvelope":
        item = self.payload.item
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["wireValue"] = 99
        self.payload = ShadowingSlottedDataclassCarrier(item=item)
        DATACLASS_SUBCLASS_HOOKS.clear()
        return self


class TypedNestedExtraLeaf(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")


class TypedNestedExtraBox(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, TypedNestedExtraLeaf] = Field(init=False)  # type: ignore[reportIncompatibleVariableOverride]
    value: int


@dataclass(slots=True)
class TypedNestedExtraCarrier:
    item: TypedNestedExtraBox


class ShadowingTypedNestedExtraCarrier(TypedNestedExtraCarrier):
    __slots__ = ()

    @property
    def __dict__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any]:
        DATACLASS_SUBCLASS_HOOKS.append("typed-extra-dict")
        raise AssertionError("__dict__ hook called during typed-extra output audit")


class ReplacingTypedNestedExtraEnvelope(BaseModel):
    payload: TypedNestedExtraCarrier

    @model_validator(mode="after")
    def replace_with_subclass(self) -> "ReplacingTypedNestedExtraEnvelope":
        item = self.payload.item
        assert item.__pydantic_extra__ is not None
        leaf = item.__pydantic_extra__["note"]
        assert leaf.__pydantic_extra__ is not None
        leaf.__pydantic_extra__["wireValue"] = 99
        self.payload = ShadowingTypedNestedExtraCarrier(item=item)
        DATACLASS_SUBCLASS_HOOKS.clear()
        return self


class SafeReplacingTypedNestedExtraEnvelope(BaseModel):
    payload: TypedNestedExtraCarrier

    @model_validator(mode="after")
    def replace_with_subclass(self) -> "SafeReplacingTypedNestedExtraEnvelope":
        self.payload = ShadowingTypedNestedExtraCarrier(item=self.payload.item)
        DATACLASS_SUBCLASS_HOOKS.clear()
        return self


class UntypedNestedExtraLeaf(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")


class UntypedNestedExtraBox(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int


@dataclass(slots=True)
class UntypedNestedExtraCarrier:
    item: UntypedNestedExtraBox


class ShadowingUntypedNestedExtraCarrier(UntypedNestedExtraCarrier):
    __slots__ = ()

    @property
    def __dict__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any]:
        DATACLASS_SUBCLASS_HOOKS.append("untyped-extra-dict")
        raise AssertionError("__dict__ hook called during untyped-extra output audit")


class ReplacingUntypedNestedExtraEnvelope(BaseModel):
    payload: UntypedNestedExtraCarrier

    @model_validator(mode="after")
    def replace_with_subclass(self) -> "ReplacingUntypedNestedExtraEnvelope":
        item = self.payload.item
        assert item.__pydantic_extra__ is not None
        leaf = UntypedNestedExtraLeaf.model_validate(item.__pydantic_extra__["note"])
        assert leaf.__pydantic_extra__ is not None
        leaf.__pydantic_extra__["wireValue"] = 99
        item.__pydantic_extra__["note"] = leaf
        self.payload = ShadowingUntypedNestedExtraCarrier(item=item)
        DATACLASS_SUBCLASS_HOOKS.clear()
        return self


class SafeReplacingUntypedNestedExtraEnvelope(BaseModel):
    payload: UntypedNestedExtraCarrier

    @model_validator(mode="after")
    def replace_with_subclass(self) -> "SafeReplacingUntypedNestedExtraEnvelope":
        item = self.payload.item
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["note"] = UntypedNestedExtraLeaf.model_validate(
            item.__pydantic_extra__["note"]
        )
        self.payload = ShadowingUntypedNestedExtraCarrier(item=item)
        DATACLASS_SUBCLASS_HOOKS.clear()
        return self


MODEL_EXTRA_STORAGE_HOOKS: list[str] = []


def _model_extra_storage_descriptor() -> MemberDescriptorType:
    for base in type.__getattribute__(BaseModel, "__mro__"):
        descriptor = type.__getattribute__(base, "__dict__").get("__pydantic_extra__")
        if type(descriptor) is MemberDescriptorType:
            return descriptor
    raise AssertionError("BaseModel extra storage descriptor not found")


def _model_dict_storage_descriptor() -> GetSetDescriptorType:
    for base in type.__getattribute__(BaseModel, "__mro__"):
        descriptor = type.__getattribute__(base, "__dict__").get("__dict__")
        if type(descriptor) is GetSetDescriptorType:
            return descriptor
    raise AssertionError("BaseModel dict storage descriptor not found")


class ShadowingModelExtraOutput(AliasedExtraOutput):
    @property
    def __pydantic_extra__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any] | None:
        MODEL_EXTRA_STORAGE_HOOKS.append("extra-get")
        if len(MODEL_EXTRA_STORAGE_HOOKS) == 1:
            return {"note": "decoy"}
        return MemberDescriptorType.__get__(
            _model_extra_storage_descriptor(), self, type(self)
        )

    @__pydantic_extra__.setter
    def __pydantic_extra__(  # type: ignore[reportIncompatibleVariableOverride]
        self, value: dict[str, Any] | None
    ) -> None:
        MemberDescriptorType.__set__(_model_extra_storage_descriptor(), self, value)


class ReplacingModelExtraStorageEnvelope(BaseModel):
    payload: SlottedNestedDataclassCarrier

    @model_validator(mode="after")
    def replace_with_shadowing_model(self) -> "ReplacingModelExtraStorageEnvelope":
        replacement = ShadowingModelExtraOutput.model_construct(value=7)
        MemberDescriptorType.__set__(
            _model_extra_storage_descriptor(), replacement, {"wireValue": 99}
        )
        self.payload = ShadowingSlottedDataclassCarrier(item=replacement)
        MODEL_EXTRA_STORAGE_HOOKS.clear()
        return self


TAGGED_EXTRA_STORAGE_HOOKS: list[str] = []


class SafeTaggedExtraOutput(BaseModel):
    kind: Literal["safe"] = Field(validation_alias="tag", serialization_alias="outKind")
    value: int


class CollisionTaggedExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: Literal["collision"] = Field(
        validation_alias="tag", serialization_alias="outKind"
    )
    value: int = Field(serialization_alias="wireValue")


class ShadowingTaggedExtraOutput(CollisionTaggedExtraOutput):
    @property
    def __pydantic_extra__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any] | None:
        TAGGED_EXTRA_STORAGE_HOOKS.append("extra-get")
        raise AssertionError("application extra property executed")

    @__pydantic_extra__.setter
    def __pydantic_extra__(  # type: ignore[reportIncompatibleVariableOverride]
        self, value: dict[str, Any] | None
    ) -> None:
        MemberDescriptorType.__set__(_model_extra_storage_descriptor(), self, value)


TaggedExtraOutput = Annotated[
    SafeTaggedExtraOutput | CollisionTaggedExtraOutput,
    Field(discriminator="kind"),
]


class ReplacingTaggedExtraStorageEnvelope(BaseModel):
    item: TaggedExtraOutput

    @model_validator(mode="after")
    def replace_with_shadowing_model(self) -> "ReplacingTaggedExtraStorageEnvelope":
        replacement = ShadowingTaggedExtraOutput.model_construct(value=7)
        MemberDescriptorType.__set__(
            _model_extra_storage_descriptor(),
            replacement,
            {"tag": "collision", "note": "safe"},
        )
        self.item = replacement
        TAGGED_EXTRA_STORAGE_HOOKS.clear()
        return self


MODEL_DICT_STORAGE_HOOKS: list[str] = []


class NestedExtraOutput(BaseModel):
    item: AliasedExtraOutput


class ShadowingModelDictOutput(NestedExtraOutput):
    @property
    def __dict__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any]:
        MODEL_DICT_STORAGE_HOOKS.append("dict-get")
        if len(MODEL_DICT_STORAGE_HOOKS) == 1:
            return {}
        return GetSetDescriptorType.__get__(
            _model_dict_storage_descriptor(), self, type(self)
        )

    @__dict__.setter
    def __dict__(  # type: ignore[reportIncompatibleVariableOverride]
        self, value: dict[str, Any]
    ) -> None:
        GetSetDescriptorType.__set__(_model_dict_storage_descriptor(), self, value)


class ReplacingModelDictStorageEnvelope(BaseModel):
    payload: NestedExtraOutput

    @model_validator(mode="after")
    def replace_with_shadowing_model(self) -> "ReplacingModelDictStorageEnvelope":
        item = AliasedExtraOutput.model_construct(value=7)
        MemberDescriptorType.__set__(
            _model_extra_storage_descriptor(), item, {"wireValue": 99}
        )
        replacement = ShadowingModelDictOutput.model_construct(item=item)
        self.payload = replacement
        MODEL_DICT_STORAGE_HOOKS.clear()
        return self


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


def test_dataclass_subclass_cannot_hide_nested_model_extra_collision():
    DATACLASS_SUBCLASS_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(ReplacingDataclassSubclassEnvelope)
        ).validate_python({"payload": {"item": {"value": 7}}})

    assert DATACLASS_SUBCLASS_HOOKS == []


def test_dataclass_subclass_cannot_hide_collision_in_typed_model_extra():
    DATACLASS_SUBCLASS_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(ReplacingTypedNestedExtraEnvelope)
        ).validate_python({"payload": {"item": {"value": 1, "note": {"value": 7}}}})

    assert DATACLASS_SUBCLASS_HOOKS == []


def test_typed_model_extra_in_valid_dataclass_subclass_remains_supported():
    DATACLASS_SUBCLASS_HOOKS.clear()
    validator = _compile_output_validator(
        TypeAdapter(SafeReplacingTypedNestedExtraEnvelope)
    )

    validated = validator.validate_python(
        {"payload": {"item": {"value": 1, "note": {"value": 7}}}}
    )

    assert validated.model_dump(mode="json", by_alias=True) == {
        "payload": {"item": {"value": 1, "note": {"wireValue": 7}}}
    }
    assert DATACLASS_SUBCLASS_HOOKS == []


def test_dataclass_subclass_cannot_hide_collision_in_untyped_model_extra():
    DATACLASS_SUBCLASS_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(ReplacingUntypedNestedExtraEnvelope)
        ).validate_python({"payload": {"item": {"value": 1, "note": {"value": 7}}}})

    assert DATACLASS_SUBCLASS_HOOKS == []


def test_untyped_model_extra_in_valid_dataclass_subclass_remains_supported():
    DATACLASS_SUBCLASS_HOOKS.clear()
    validator = _compile_output_validator(
        TypeAdapter(SafeReplacingUntypedNestedExtraEnvelope)
    )

    validated = validator.validate_python(
        {"payload": {"item": {"value": 1, "note": {"value": 7}}}}
    )

    assert validated.model_dump(mode="json", by_alias=True) == {
        "payload": {"item": {"value": 1, "note": {"wireValue": 7}}}
    }
    assert DATACLASS_SUBCLASS_HOOKS == []


def test_model_extra_property_cannot_hide_nested_collision():
    MODEL_EXTRA_STORAGE_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(ReplacingModelExtraStorageEnvelope)
        ).validate_python({"payload": {"item": {"value": 7}}})

    assert MODEL_EXTRA_STORAGE_HOOKS == []


def test_tagged_union_discriminator_uses_trusted_extra_storage():
    TAGGED_EXTRA_STORAGE_HOOKS.clear()

    result = _compile_output_validator(
        TypeAdapter(ReplacingTaggedExtraStorageEnvelope)
    ).validate_python({"item": {"tag": "collision", "value": 7}})

    assert result.item.value == 7
    assert TAGGED_EXTRA_STORAGE_HOOKS == []


def test_model_dict_property_cannot_hide_nested_collision():
    MODEL_DICT_STORAGE_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(ReplacingModelDictStorageEnvelope)
        ).validate_python({"payload": {"item": {"value": 7}}})

    assert MODEL_DICT_STORAGE_HOOKS == []


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


def test_http_rejects_nested_collision_inside_dataclass_subclass():
    DATACLASS_SUBCLASS_HOOKS.clear()
    summon = _direct_summon(
        ReplacingDataclassSubclassEnvelope,
        {"payload": {"item": {"value": 7}}},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"wireValue"') == 0
    assert DATACLASS_SUBCLASS_HOOKS == []


def test_runtime_rejects_typed_model_extra_collision_inside_dataclass_subclass():
    DATACLASS_SUBCLASS_HOOKS.clear()
    summon = _direct_summon(
        ReplacingTypedNestedExtraEnvelope,
        {"payload": {"item": {"value": 1, "note": {"value": 7}}}},
    )

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    assert DATACLASS_SUBCLASS_HOOKS == []


def test_http_rejects_typed_model_extra_collision_inside_dataclass_subclass():
    DATACLASS_SUBCLASS_HOOKS.clear()
    summon = _direct_summon(
        ReplacingTypedNestedExtraEnvelope,
        {"payload": {"item": {"value": 1, "note": {"value": 7}}}},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"wireValue"') == 0
    assert DATACLASS_SUBCLASS_HOOKS == []


def test_runtime_rejects_untyped_model_extra_collision_inside_dataclass_subclass():
    DATACLASS_SUBCLASS_HOOKS.clear()
    summon = _direct_summon(
        ReplacingUntypedNestedExtraEnvelope,
        {"payload": {"item": {"value": 1, "note": {"value": 7}}}},
    )

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    assert DATACLASS_SUBCLASS_HOOKS == []


def test_http_rejects_untyped_model_extra_collision_inside_dataclass_subclass():
    DATACLASS_SUBCLASS_HOOKS.clear()
    summon = _direct_summon(
        ReplacingUntypedNestedExtraEnvelope,
        {"payload": {"item": {"value": 1, "note": {"value": 7}}}},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"wireValue"') == 0
    assert DATACLASS_SUBCLASS_HOOKS == []


def test_http_model_extra_property_cannot_hide_nested_collision():
    MODEL_EXTRA_STORAGE_HOOKS.clear()
    summon = _direct_summon(
        ReplacingModelExtraStorageEnvelope,
        {"payload": {"item": {"value": 7}}},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"wireValue"') == 0
    assert MODEL_EXTRA_STORAGE_HOOKS == []


def test_http_model_dict_property_cannot_hide_nested_collision():
    MODEL_DICT_STORAGE_HOOKS.clear()
    summon = _direct_summon(
        ReplacingModelDictStorageEnvelope,
        {"payload": {"item": {"value": 7}}},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"wireValue"') == 0
    assert MODEL_DICT_STORAGE_HOOKS == []


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


class MutatingTypedDictEnvelope(BaseModel):
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def add_nested_collision(self) -> "MutatingTypedDictEnvelope":
        self.item["wireValue"] = 99  # type: ignore[typeddict-unknown-key]
        return self


class SafeMutatingTypedDictEnvelope(BaseModel):
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def add_nested_extra(self) -> "SafeMutatingTypedDictEnvelope":
        self.item["note"] = "safe"  # type: ignore[typeddict-unknown-key]
        return self


NONEXACT_KEY_HOOKS: list[str] = []


class HostileStringKey(str):
    def __hash__(self) -> int:
        NONEXACT_KEY_HOOKS.append("hash")
        return str.__hash__(self)

    def __eq__(self, other: object) -> bool:
        NONEXACT_KEY_HOOKS.append("eq")
        raise AssertionError("equality hook called during output audit")

    def __repr__(self) -> str:
        NONEXACT_KEY_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")

    def __str__(self) -> str:
        NONEXACT_KEY_HOOKS.append("str")
        raise AssertionError("string hook called during output audit")


class NonexactKeyModelOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")

    @model_validator(mode="after")
    def add_nonexact_key(self) -> "NonexactKeyModelOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__[HostileStringKey("wireValue")] = 99
        NONEXACT_KEY_HOOKS.clear()
        return self


class SafeExactKeyModelOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: int = Field(serialization_alias="wireValue")

    @model_validator(mode="after")
    def add_exact_key(self) -> "SafeExactKeyModelOutput":
        assert self.__pydantic_extra__ is not None
        self.__pydantic_extra__["note"] = "safe"
        return self


class NonexactKeyTypedDictEnvelope(BaseModel):
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def replace_nested_mapping(self) -> "NonexactKeyTypedDictEnvelope":
        replacement = dict(self.item)
        replacement[HostileStringKey("wireValue")] = 99
        NONEXACT_KEY_HOOKS.clear()
        self.item = replacement  # type: ignore[assignment]
        return self


class SafeExactKeyTypedDictEnvelope(BaseModel):
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def replace_nested_mapping(self) -> "SafeExactKeyTypedDictEnvelope":
        self.item = {**self.item, "note": "safe"}  # type: ignore[assignment,typeddict-unknown-key]
        return self


class ReplacingTypedDictEnvelope(BaseModel):
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def replace_nested_mapping(self) -> "ReplacingTypedDictEnvelope":
        self.item = {**self.item, "wireValue": 99}  # type: ignore[typeddict-unknown-key]
        return self


MAPPING_AUDIT_HOOKS: list[str] = []


class HostileDict(dict[str, Any]):
    def __iter__(self):
        MAPPING_AUDIT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def keys(self):
        MAPPING_AUDIT_HOOKS.append("keys")
        raise AssertionError("keys hook called during output audit")

    def items(self):
        MAPPING_AUDIT_HOOKS.append("items")
        raise AssertionError("items hook called during output audit")

    def values(self):
        MAPPING_AUDIT_HOOKS.append("values")
        raise AssertionError("values hook called during output audit")

    def __eq__(self, other: object) -> bool:
        MAPPING_AUDIT_HOOKS.append("eq")
        raise AssertionError("equality hook called during output audit")

    def __repr__(self) -> str:
        MAPPING_AUDIT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")


class HostileReplacingTypedDictEnvelope(BaseModel):
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def replace_nested_mapping(self) -> "HostileReplacingTypedDictEnvelope":
        self.item = HostileDict({**self.item, "wireValue": 99})  # type: ignore[assignment]
        MAPPING_AUDIT_HOOKS.clear()
        return self


SET_AUDIT_HOOKS: list[str] = []


class FrozenAllowedExtraOutput(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    value: int = Field(serialization_alias="wireValue")

    def __hash__(self) -> int:
        SET_AUDIT_HOOKS.append("hash")
        return object.__hash__(self)

    def __eq__(self, other: object) -> bool:
        SET_AUDIT_HOOKS.append("eq")
        return self is other

    @model_serializer(mode="wrap")
    def serialize(self, handler: Any) -> Any:
        SET_AUDIT_HOOKS.append("serializer")
        return handler(self)

    def __copy__(self):
        SET_AUDIT_HOOKS.append("copy")
        raise AssertionError("copy hook called during output validation")

    def __repr__(self) -> str:
        SET_AUDIT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output validation")


class HostileSet(set[FrozenAllowedExtraOutput]):
    def __iter__(self):
        SET_AUDIT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def __repr__(self) -> str:
        SET_AUDIT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")


class HostileFrozenSet(frozenset[FrozenAllowedExtraOutput]):
    def __iter__(self):
        SET_AUDIT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def __repr__(self) -> str:
        SET_AUDIT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")


class MutatingSetEnvelope(BaseModel):
    items: set[FrozenAllowedExtraOutput]

    @model_validator(mode="after")
    def add_nested_collision(self) -> "MutatingSetEnvelope":
        item = next(set.__iter__(self.items))
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["wireValue"] = 99
        object.__setattr__(self, "items", HostileSet(set.__iter__(self.items)))
        SET_AUDIT_HOOKS.clear()
        return self


class SafeMutatingSetEnvelope(BaseModel):
    items: set[FrozenAllowedExtraOutput] | frozenset[FrozenAllowedExtraOutput]

    @model_validator(mode="after")
    def add_nested_extra(self) -> "SafeMutatingSetEnvelope":
        item = next(
            frozenset.__iter__(self.items)
            if isinstance(self.items, frozenset)
            else set.__iter__(self.items)
        )
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["note"] = "safe"
        return self


class MutatingFrozenSetEnvelope(BaseModel):
    items: frozenset[FrozenAllowedExtraOutput]

    @model_validator(mode="after")
    def add_nested_collision(self) -> "MutatingFrozenSetEnvelope":
        item = next(frozenset.__iter__(self.items))
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["wireValue"] = 99
        object.__setattr__(
            self, "items", HostileFrozenSet(frozenset.__iter__(self.items))
        )
        SET_AUDIT_HOOKS.clear()
        return self


class SafeMutatingFrozenSetEnvelope(BaseModel):
    items: frozenset[FrozenAllowedExtraOutput]

    @model_validator(mode="after")
    def add_nested_extra(self) -> "SafeMutatingFrozenSetEnvelope":
        item = next(frozenset.__iter__(self.items))
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["note"] = "safe"
        return self


DEQUE_AUDIT_HOOKS: list[str] = []


class HostileDeque(deque[AliasedExtraOutput]):
    def __iter__(self):
        DEQUE_AUDIT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def __getitem__(self, index: SupportsIndex):
        DEQUE_AUDIT_HOOKS.append("getitem")
        raise AssertionError("getitem hook called during output audit")

    def __len__(self) -> int:
        DEQUE_AUDIT_HOOKS.append("len")
        raise AssertionError("length hook called during output audit")

    def __repr__(self) -> str:
        DEQUE_AUDIT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")


class MutatingDequeEnvelope(BaseModel):
    items: deque[AliasedExtraOutput]

    @model_validator(mode="after")
    def add_nested_collision(self) -> "MutatingDequeEnvelope":
        item = deque.__getitem__(self.items, 0)
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["wireValue"] = 99
        return self


class SafeMutatingDequeEnvelope(BaseModel):
    items: deque[AliasedExtraOutput]

    @model_validator(mode="after")
    def add_nested_extra(self) -> "SafeMutatingDequeEnvelope":
        item = deque.__getitem__(self.items, 0)
        assert item.__pydantic_extra__ is not None
        item.__pydantic_extra__["note"] = "safe"
        return self


class HostileMutatingDequeEnvelope(BaseModel):
    items: deque[AliasedExtraOutput]

    @model_validator(mode="after")
    def replace_deque_with_hostile_subclass(self) -> "HostileMutatingDequeEnvelope":
        object.__setattr__(self, "items", HostileDeque(deque.__iter__(self.items)))
        DEQUE_AUDIT_HOOKS.clear()
        return self


class CyclicDequeEnvelope(BaseModel):
    items: deque[Any]

    @model_validator(mode="after")
    def add_self_reference(self) -> "CyclicDequeEnvelope":
        deque.append(self.items, self)
        return self


CONTAINER_REPLACEMENT_HOOKS: list[str] = []


class HostileIterable:
    def __iter__(self):
        CONTAINER_REPLACEMENT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def __repr__(self) -> str:
        CONTAINER_REPLACEMENT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")

    def __eq__(self, other: object) -> bool:
        CONTAINER_REPLACEMENT_HOOKS.append("eq")
        raise AssertionError("equality hook called during output audit")

    def __hash__(self) -> int:
        CONTAINER_REPLACEMENT_HOOKS.append("hash")
        raise AssertionError("hash hook called during output audit")


class HostileList(list[int]):
    def __iter__(self):
        CONTAINER_REPLACEMENT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def __repr__(self) -> str:
        CONTAINER_REPLACEMENT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")

    def __eq__(self, other: object) -> bool:
        CONTAINER_REPLACEMENT_HOOKS.append("eq")
        raise AssertionError("equality hook called during output audit")


class HostileTuple(tuple[int, ...]):
    def __iter__(self):
        CONTAINER_REPLACEMENT_HOOKS.append("iter")
        raise AssertionError("iteration hook called during output audit")

    def __repr__(self) -> str:
        CONTAINER_REPLACEMENT_HOOKS.append("repr")
        raise AssertionError("repr hook called during output audit")

    def __eq__(self, other: object) -> bool:
        CONTAINER_REPLACEMENT_HOOKS.append("eq")
        raise AssertionError("equality hook called during output audit")


def _replace_with_hostile_iterable(value: Any) -> HostileIterable:
    return HostileIterable()


def _replace_deque_with_collision_generator(value: deque[AliasedExtraOutput]) -> Any:
    item = deque.__getitem__(value, 0)
    assert item.__pydantic_extra__ is not None
    item.__pydantic_extra__["wireValue"] = 99

    def generate():
        CONTAINER_REPLACEMENT_HOOKS.append("iter")
        yield item

    return generate()


HostileListOutput = Annotated[list[int], AfterValidator(_replace_with_hostile_iterable)]
HostileTupleOutput = Annotated[
    tuple[int, ...], AfterValidator(_replace_with_hostile_iterable)
]
HostileDictOutput = Annotated[
    dict[str, int], AfterValidator(_replace_with_hostile_iterable)
]
HostileSetOutput = Annotated[set[int], AfterValidator(_replace_with_hostile_iterable)]
HostileFrozenSetOutput = Annotated[
    frozenset[int], AfterValidator(_replace_with_hostile_iterable)
]
HostileDequeOutput = Annotated[
    deque[int], AfterValidator(_replace_with_hostile_iterable)
]
HostileUnionOutput = HostileListOutput | int
HostileListSubclassOutput = Annotated[
    list[int], AfterValidator(lambda value: HostileList(value))
]
HostileTupleSubclassOutput = Annotated[
    tuple[int, ...], AfterValidator(lambda value: HostileTuple(value))
]
GeneratorDequeOutput = Annotated[
    deque[AliasedExtraOutput], AfterValidator(_replace_deque_with_collision_generator)
]


class GeneratorReplacingDequeEnvelope(BaseModel):
    items: deque[AliasedExtraOutput]

    @model_validator(mode="after")
    def replace_deque_with_generator(self) -> "GeneratorReplacingDequeEnvelope":
        object.__setattr__(
            self,
            "items",
            _replace_deque_with_collision_generator(self.items),
        )
        return self


class ListBranchModel(BaseModel):
    items: list[int]


class TupleBranchModel(BaseModel):
    items: tuple[int, ...]


class ListBranchTypedDict(TypedDict):
    items: list[int]


class TupleBranchTypedDict(TypedDict):
    items: tuple[int, ...]


class LeftBranchTypedDict(TypedDict):
    left: list[int]


class RightBranchTypedDict(TypedDict):
    right: tuple[int, ...]


class SafeTaggedTypedDict(TypedDict):
    kind: Literal["safe"]
    value: int


class CollisionTaggedTypedDict(TypedDict):
    kind: Literal["collision"]
    value: Annotated[int, Field(serialization_alias="wireValue")]


CollisionTaggedTypedDict.__pydantic_config__ = ConfigDict(  # type: ignore[attr-defined]
    extra="allow"
)

TaggedTypedDict = Annotated[
    SafeTaggedTypedDict | CollisionTaggedTypedDict,
    Field(discriminator="kind"),
]
ReversedTaggedTypedDict = Annotated[
    CollisionTaggedTypedDict | SafeTaggedTypedDict,
    Field(discriminator="kind"),
]
UntaggedTypedDict = SafeTaggedTypedDict | CollisionTaggedTypedDict
ReversedUntaggedTypedDict = CollisionTaggedTypedDict | SafeTaggedTypedDict


class TaggedTypedDictEnvelope(BaseModel):
    item: TaggedTypedDict

    @model_validator(mode="after")
    def replace_selected_mapping(self) -> "TaggedTypedDictEnvelope":
        self.item = {**self.item, "wireValue": 99}  # type: ignore[assignment,typeddict-unknown-key]
        return self


class ReversedTaggedTypedDictEnvelope(BaseModel):
    item: ReversedTaggedTypedDict

    @model_validator(mode="after")
    def replace_selected_mapping(self) -> "ReversedTaggedTypedDictEnvelope":
        self.item = {**self.item, "wireValue": 99}  # type: ignore[assignment,typeddict-unknown-key]
        return self


class AliasedSafeTaggedTypedDict(TypedDict):
    kind: Annotated[Literal["safe"], Field(validation_alias="tag")]
    value: int


class AliasedCollisionTaggedTypedDict(TypedDict):
    kind: Annotated[Literal["collision"], Field(validation_alias="tag")]
    value: Annotated[int, Field(serialization_alias="wireValue")]


AliasedCollisionTaggedTypedDict.__pydantic_config__ = ConfigDict(  # type: ignore[attr-defined]
    extra="allow"
)

AliasedTaggedTypedDict = Annotated[
    AliasedSafeTaggedTypedDict | AliasedCollisionTaggedTypedDict,
    Field(discriminator="kind"),
]


class AliasPathTaggedTypedDictEnvelope(BaseModel):
    item: AliasedTaggedTypedDict

    @model_validator(mode="after")
    def replace_with_alias_storage(self) -> "AliasPathTaggedTypedDictEnvelope":
        self.item = {  # type: ignore[assignment]
            "tag": self.item["kind"],
            "value": self.item["value"],
            "wireValue": 99,
        }
        return self


class UntaggedTypedDictEnvelope(BaseModel):
    item: UntaggedTypedDict

    @model_validator(mode="after")
    def replace_selected_mapping(self) -> "UntaggedTypedDictEnvelope":
        self.item = {**self.item, "wireValue": 99}  # type: ignore[assignment,typeddict-unknown-key]
        return self


class ReversedUntaggedTypedDictEnvelope(BaseModel):
    item: ReversedUntaggedTypedDict

    @model_validator(mode="after")
    def replace_selected_mapping(self) -> "ReversedUntaggedTypedDictEnvelope":
        self.item = {**self.item, "wireValue": 99}  # type: ignore[assignment,typeddict-unknown-key]
        return self


NaNLiteral = Literal.__getitem__((float("nan"),))
FloatOneLiteral = Literal.__getitem__((1.0,))


class SafeFloatLiteralTypedDict(TypedDict):
    kind: FloatOneLiteral  # type: ignore[valid-type]
    value: int


class NaNCollisionTypedDict(TypedDict):
    kind: NaNLiteral  # type: ignore[valid-type]
    value: Annotated[int, Field(serialization_alias="wireValue")]


NaNCollisionTypedDict.__pydantic_config__ = ConfigDict(  # type: ignore[attr-defined]
    extra="allow"
)


class NaNLiteralEnvelope(BaseModel):
    item: SafeFloatLiteralTypedDict | NaNCollisionTypedDict

    @model_validator(mode="after")
    def replace_selected_mapping(self) -> "NaNLiteralEnvelope":
        self.item = {**self.item, "wireValue": 99}  # type: ignore[assignment,typeddict-unknown-key]
        return self


TAGGED_STORAGE_HOOKS: list[str] = []


class HostileTaggedDict(dict[str, Any]):
    def __iter__(self):
        TAGGED_STORAGE_HOOKS.append("iter")
        raise AssertionError("iteration hook called during tagged-union audit")

    def __getitem__(self, key: str):
        TAGGED_STORAGE_HOOKS.append("getitem")
        raise AssertionError("getitem hook called during tagged-union audit")

    def __eq__(self, other: object) -> bool:
        TAGGED_STORAGE_HOOKS.append("eq")
        raise AssertionError("equality hook called during tagged-union audit")

    def __repr__(self) -> str:
        TAGGED_STORAGE_HOOKS.append("repr")
        raise AssertionError("repr hook called during tagged-union audit")


class HostileTaggedTypedDictEnvelope(BaseModel):
    item: TaggedTypedDict

    @model_validator(mode="after")
    def replace_selected_mapping(self) -> "HostileTaggedTypedDictEnvelope":
        self.item = HostileTaggedDict({**self.item, "wireValue": 99})  # type: ignore[assignment]
        TAGGED_STORAGE_HOOKS.clear()
        return self


class SafeTaggedModel(BaseModel):
    kind: Literal["safe"]
    value: int


class CollisionTaggedModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: Literal["collision"]
    value: int = Field(serialization_alias="wireValue")


TaggedModel = Annotated[
    SafeTaggedModel | CollisionTaggedModel,
    Field(discriminator="kind"),
]
ReversedTaggedModel = Annotated[
    CollisionTaggedModel | SafeTaggedModel,
    Field(discriminator="kind"),
]


class TaggedModelEnvelope(BaseModel):
    item: TaggedModel

    @model_validator(mode="after")
    def add_selected_collision(self) -> "TaggedModelEnvelope":
        assert isinstance(self.item, CollisionTaggedModel)
        assert self.item.__pydantic_extra__ is not None
        self.item.__pydantic_extra__["wireValue"] = 99
        return self


class ReversedTaggedModelEnvelope(BaseModel):
    item: ReversedTaggedModel

    @model_validator(mode="after")
    def add_selected_collision(self) -> "ReversedTaggedModelEnvelope":
        assert isinstance(self.item, CollisionTaggedModel)
        assert self.item.__pydantic_extra__ is not None
        self.item.__pydantic_extra__["wireValue"] = 99
        return self


class HostileCollisionTaggedModel(CollisionTaggedModel):
    def __getattribute__(self, name: str) -> Any:
        if name in {"kind", "value", "__dict__", "__pydantic_extra__"}:
            TAGGED_STORAGE_HOOKS.append("getattribute")
            raise AssertionError("attribute hook called during tagged-union audit")
        return object.__getattribute__(self, name)

    def __eq__(self, other: object) -> bool:
        TAGGED_STORAGE_HOOKS.append("eq")
        raise AssertionError("equality hook called during tagged-union audit")

    def __repr__(self) -> str:
        TAGGED_STORAGE_HOOKS.append("repr")
        raise AssertionError("repr hook called during tagged-union audit")


class HostileTaggedModelEnvelope(BaseModel):
    item: TaggedModel

    @model_validator(mode="after")
    def replace_selected_model(self) -> "HostileTaggedModelEnvelope":
        replacement = HostileCollisionTaggedModel.model_construct(
            kind="collision", value=7
        )
        object.__setattr__(replacement, "__pydantic_extra__", {"wireValue": 99})
        object.__setattr__(self, "item", replacement)
        TAGGED_STORAGE_HOOKS.clear()
        return self


@dataclass(slots=True, frozen=True)
class SafeTaggedDataclass:
    kind: Literal["safe"]
    value: int


@dataclass(slots=True, frozen=True)
class CollisionTaggedDataclass:
    kind: Literal["collision"]
    item: AllowedExtraTypedDict

    @model_validator(mode="after")
    def replace_nested_mapping(self) -> "CollisionTaggedDataclass":
        object.__setattr__(self, "item", {**self.item, "wireValue": 99})
        return self


TaggedDataclass = Annotated[
    SafeTaggedDataclass | CollisionTaggedDataclass,
    Field(discriminator="kind"),
]


DATACLASS_STORAGE_HOOKS: list[str] = []


@dataclass(slots=True, frozen=True)
class SlottedDataclassOutput:
    value: int


class ShadowedDictSlottedDataclass(SlottedDataclassOutput):
    __slots__ = ()

    @property
    def __dict__(  # type: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any]:
        DATACLASS_STORAGE_HOOKS.append("dict")
        raise AssertionError("dict property called during dataclass audit")

    def __repr__(self) -> str:
        DATACLASS_STORAGE_HOOKS.append("repr")
        raise AssertionError("repr hook called during dataclass audit")

    def __eq__(self, other: object) -> bool:
        DATACLASS_STORAGE_HOOKS.append("eq")
        raise AssertionError("equality hook called during dataclass audit")

    def __hash__(self) -> int:
        DATACLASS_STORAGE_HOOKS.append("hash")
        raise AssertionError("hash hook called during dataclass audit")


class ShadowedDictDataclassEnvelope(BaseModel):
    item: SlottedDataclassOutput

    @model_validator(mode="after")
    def replace_dataclass(self) -> "ShadowedDictDataclassEnvelope":
        replacement = object.__new__(ShadowedDictSlottedDataclass)
        object.__setattr__(replacement, "value", self.item.value)
        object.__setattr__(self, "item", replacement)
        DATACLASS_STORAGE_HOOKS.clear()
        return self


class HostileSafeTaggedDataclass(SafeTaggedDataclass):
    def __getattribute__(self, name: str) -> Any:
        if name in {"kind", "value"}:
            DATACLASS_STORAGE_HOOKS.append("getattribute")
            raise AssertionError("attribute hook called during tagged-union audit")
        return object.__getattribute__(self, name)

    def __getstate__(self) -> Any:
        DATACLASS_STORAGE_HOOKS.append("getstate")
        raise AssertionError("state hook called during tagged-union audit")

    def __repr__(self) -> str:
        DATACLASS_STORAGE_HOOKS.append("repr")
        raise AssertionError("repr hook called during tagged-union audit")

    def __eq__(self, other: object) -> bool:
        DATACLASS_STORAGE_HOOKS.append("eq")
        raise AssertionError("equality hook called during tagged-union audit")

    def __hash__(self) -> int:
        DATACLASS_STORAGE_HOOKS.append("hash")
        raise AssertionError("hash hook called during tagged-union audit")


class HostileTaggedDataclassEnvelope(BaseModel):
    item: TaggedDataclass

    @model_validator(mode="after")
    def replace_selected_dataclass(self) -> "HostileTaggedDataclassEnvelope":
        replacement = object.__new__(HostileSafeTaggedDataclass)
        object.__setattr__(replacement, "kind", "safe")
        object.__setattr__(replacement, "value", self.item.value)
        object.__setattr__(self, "item", replacement)
        DATACLASS_STORAGE_HOOKS.clear()
        return self


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


@pytest.mark.parametrize(
    "output",
    [
        MutatingTypedDictEnvelope,
        MutatingTypedDictEnvelope | int,
        RootModel[MutatingTypedDictEnvelope],
    ],
)
def test_parent_validator_cannot_add_nested_typed_dict_alias_collision(output: Any):
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(
            {"item": {"value": 7}}
        )


def test_parent_validator_can_add_nested_typed_dict_noncolliding_extra():
    validated = _compile_output_validator(
        TypeAdapter(SafeMutatingTypedDictEnvelope)
    ).validate_python({"item": {"value": 7}})

    assert validated.model_dump(mode="json", by_alias=True) == {
        "item": {"wireValue": 7, "note": "safe"}
    }


@pytest.mark.parametrize(
    "output,value",
    [
        (NonexactKeyModelOutput, {"value": 7}),
        (NonexactKeyTypedDictEnvelope, {"item": {"value": 7}}),
    ],
)
def test_post_validation_nonexact_string_keys_are_rejected_without_hooks(
    output: Any, value: Any
):
    NONEXACT_KEY_HOOKS.clear()

    with pytest.raises(ValidationError, match="exact str"):
        _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert NONEXACT_KEY_HOOKS == []


@pytest.mark.parametrize(
    "output,value,expected",
    [
        (SafeExactKeyModelOutput, {"value": 7}, {"wireValue": 7, "note": "safe"}),
        (
            SafeExactKeyTypedDictEnvelope,
            {"item": {"value": 7}},
            {"item": {"wireValue": 7, "note": "safe"}},
        ),
    ],
)
def test_post_validation_safe_exact_string_keys_remain_supported(
    output: Any, value: Any, expected: Any
):
    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert (
        TypeAdapter(output).dump_python(validated, mode="json", by_alias=True)
        == expected
    )


@pytest.mark.parametrize(
    "output,result,expected",
    [
        (SafeExactKeyModelOutput, {"value": 7}, {"wireValue": 7, "note": "safe"}),
        (
            SafeExactKeyTypedDictEnvelope,
            {"item": {"value": 7}},
            {"item": {"wireValue": 7, "note": "safe"}},
        ),
    ],
)
def test_runtime_and_http_preserve_safe_exact_string_keys(
    output: Any,
    result: Any,
    expected: Any,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")
    summon = _direct_summon(output, result)

    runtime_result = asyncio.run(
        Runtime(model="test").call(summon.endpoints[0], {"value": 7})
    )
    assert (
        TypeAdapter(output).dump_python(runtime_result, mode="json", by_alias=True)
        == expected
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    "output,result",
    [
        (NonexactKeyModelOutput, {"value": 7}),
        (NonexactKeyTypedDictEnvelope, {"item": {"value": 7}}),
    ],
)
def test_runtime_and_http_reject_nonexact_string_keys_without_hooks(
    output: Any, result: Any, monkeypatch: pytest.MonkeyPatch
):
    NONEXACT_KEY_HOOKS.clear()
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")
    summon = _direct_summon(output, result)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(Runtime(model="test").call(summon.endpoints[0], {"value": 7}))
    assert NONEXACT_KEY_HOOKS == []

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert NONEXACT_KEY_HOOKS == []


@pytest.mark.parametrize(
    "output,value",
    [
        (ReplacingTypedDictEnvelope, {"item": {"value": 7}}),
        (ReplacingTypedDictEnvelope | int, {"item": {"value": 7}}),
        (RootModel[ReplacingTypedDictEnvelope], {"item": {"value": 7}}),
        (list[ReplacingTypedDictEnvelope], [{"item": {"value": 7}}]),
        (tuple[ReplacingTypedDictEnvelope], [{"item": {"value": 7}}]),
        (
            tuple[ReplacingTypedDictEnvelope, ...],
            [{"item": {"value": 7}}, {"item": {"value": 8}}],
        ),
        (dict[str, ReplacingTypedDictEnvelope], {"entry": {"item": {"value": 7}}}),
    ],
)
def test_final_audit_follows_schema_after_typed_dict_replacement(
    output: Any, value: Any
):
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(value)


def test_replacement_audit_does_not_call_mapping_hooks():
    MAPPING_AUDIT_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(HostileReplacingTypedDictEnvelope)
        ).validate_python({"item": {"value": 7}})

    assert MAPPING_AUDIT_HOOKS == []


def test_typed_dict_replacement_requires_exact_dict_without_calling_hooks():
    MAPPING_AUDIT_HOOKS.clear()

    with pytest.raises(ValidationError, match="dict"):
        _compile_output_validator(
            TypeAdapter(HostileReplacingTypedDictEnvelope)
        ).validate_python({"item": {"value": 7}})

    assert MAPPING_AUDIT_HOOKS == []


def test_runtime_rejects_prevalidated_model_nested_typed_dict_alias_collision():
    result = ReplacingTypedDictEnvelope.model_construct(item={"value": 7})
    summon = _direct_summon(ReplacingTypedDictEnvelope, result)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )


def test_http_rejects_prevalidated_model_nested_typed_dict_alias_collision():
    result = ReplacingTypedDictEnvelope.model_construct(item={"value": 7})
    summon = _direct_summon(ReplacingTypedDictEnvelope, result)

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert '"wireValue":7,"wireValue":99' not in response.text


@pytest.mark.parametrize(
    "output,value",
    [
        (MutatingSetEnvelope, {"items": [{"value": 7}]}),
        (MutatingSetEnvelope | int, {"items": [{"value": 7}]}),
        (RootModel[MutatingSetEnvelope], {"items": [{"value": 7}]}),
        (MutatingFrozenSetEnvelope, {"items": [{"value": 7}]}),
    ],
)
def test_parent_validator_cannot_hide_collision_in_set_or_frozenset(
    output: Any, value: Any
):
    SET_AUDIT_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert SET_AUDIT_HOOKS == []


def test_parent_validator_preserves_noncolliding_extra_in_set():
    validated = _compile_output_validator(
        TypeAdapter(SafeMutatingSetEnvelope)
    ).validate_python({"items": [{"value": 7}]})
    assert isinstance(validated.items, set)
    item = next(set.__iter__(validated.items))

    assert item.__pydantic_extra__ == {"note": "safe"}


def test_parent_validator_preserves_noncolliding_extra_in_frozenset():
    validated = _compile_output_validator(
        TypeAdapter(SafeMutatingFrozenSetEnvelope)
    ).validate_python({"items": [{"value": 7}]})
    item = next(frozenset.__iter__(validated.items))

    assert item.__pydantic_extra__ == {"note": "safe"}


def test_parent_validator_cannot_hide_collision_in_deque():
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(MutatingDequeEnvelope)).validate_python(
            {"items": [{"value": 7}]}
        )


def test_parent_validator_preserves_noncolliding_extra_in_deque():
    validated = _compile_output_validator(
        TypeAdapter(SafeMutatingDequeEnvelope)
    ).validate_python({"items": [{"value": 7}]})
    item = deque.__getitem__(validated.items, 0)

    assert type(validated.items) is deque
    assert item.__pydantic_extra__ == {"note": "safe"}


def test_deque_audit_rejects_subclass_without_calling_hooks():
    DEQUE_AUDIT_HOOKS.clear()

    with pytest.raises(ValidationError, match="deque"):
        _compile_output_validator(
            TypeAdapter(HostileMutatingDequeEnvelope)
        ).validate_python({"items": [{"value": 7}]})

    assert DEQUE_AUDIT_HOOKS == []


def test_deque_audit_stops_at_cycles():
    validated = _compile_output_validator(
        TypeAdapter(CyclicDequeEnvelope)
    ).validate_python({"items": []})

    assert deque.__len__(validated.items) == 1
    assert deque.__getitem__(validated.items, 0) is validated


@pytest.mark.parametrize(
    "output,value,container_name",
    [
        (HostileListOutput, [1], "list"),
        (HostileTupleOutput, [1], "tuple"),
        (HostileDictOutput, {"value": 1}, "dict"),
        (HostileSetOutput, [1], "set"),
        (HostileFrozenSetOutput, [1], "frozenset"),
        (HostileDequeOutput, [1], "deque"),
        (HostileListOutput | None, [1], "list"),
        (HostileUnionOutput, [1], "list"),
        (RootModel[HostileListOutput], [1], "list"),
        (HostileListSubclassOutput, [1], "list"),
        (HostileTupleSubclassOutput, [1], "tuple"),
    ],
)
def test_post_validator_must_preserve_declared_concrete_container_type(
    output: Any, value: Any, container_name: str
):
    CONTAINER_REPLACEMENT_HOOKS.clear()

    with pytest.raises(ValidationError, match=container_name):
        _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert CONTAINER_REPLACEMENT_HOOKS == []


@pytest.mark.parametrize(
    "output,value,expected_type",
    [
        (list[int], [1], list),
        (tuple[int, ...], [1], tuple),
        (dict[str, int], {"value": 1}, dict),
        (set[int], [1], set),
        (frozenset[int], [1], frozenset),
        (deque[int], [1], deque),
    ],
)
def test_declared_concrete_containers_keep_safe_pydantic_transformations(
    output: Any, value: Any, expected_type: type[Any]
):
    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert type(validated) is expected_type


@pytest.mark.parametrize(
    "output,value,inner_type",
    [
        (list[list[int]] | list[tuple[int, ...]], [[1, 2]], list),
        (list[tuple[int, ...]] | list[list[int]], [[1, 2]], list),
        (list[list[int]] | list[tuple[int, ...]], [(1, 2)], tuple),
        (list[tuple[int, ...]] | list[list[int]], [(1, 2)], tuple),
    ],
)
def test_same_outer_list_union_audits_only_the_selected_nested_container_branch(
    output: Any, value: Any, inner_type: type[Any]
):
    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert type(validated) is list
    assert type(list.__getitem__(validated, 0)) is inner_type


@pytest.mark.parametrize(
    "output,value,inner_type",
    [
        (dict[str, list[int]] | dict[str, tuple[int, ...]], {"item": [1, 2]}, list),
        (dict[str, tuple[int, ...]] | dict[str, list[int]], {"item": [1, 2]}, list),
        (dict[str, list[int]] | dict[str, tuple[int, ...]], {"item": (1, 2)}, tuple),
        (dict[str, tuple[int, ...]] | dict[str, list[int]], {"item": (1, 2)}, tuple),
    ],
)
def test_same_outer_dict_union_audits_only_the_selected_nested_container_branch(
    output: Any, value: Any, inner_type: type[Any]
):
    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert type(validated) is dict
    assert type(dict.__getitem__(validated, "item")) is inner_type


@pytest.mark.parametrize(
    "output,value",
    [
        (list[list[int]] | list[tuple[int, ...]], []),
        (list[tuple[int, ...]] | list[list[int]], []),
        (list[list[int]] | list[tuple[int, ...]], [[]]),
        (dict[str, list[int]] | dict[str, tuple[int, ...]], {}),
    ],
)
def test_ambiguous_empty_same_container_unions_preserve_pydantic_output(
    output: Any, value: Any
):
    expected = TypeAdapter(output).validate_python(value)

    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert type(validated) is type(expected)
    if type(validated) is list and list.__len__(validated):
        assert type(list.__getitem__(validated, 0)) is type(
            list.__getitem__(expected, 0)
        )


@pytest.mark.parametrize(
    "output,value,expected_model",
    [
        (
            list[ListBranchModel] | list[TupleBranchModel],
            [ListBranchModel(items=[1])],
            ListBranchModel,
        ),
        (
            list[TupleBranchModel] | list[ListBranchModel],
            [ListBranchModel(items=[1])],
            ListBranchModel,
        ),
        (
            list[ListBranchModel] | list[TupleBranchModel],
            [TupleBranchModel(items=(1,))],
            TupleBranchModel,
        ),
    ],
)
def test_same_container_model_unions_follow_exact_model_instances(
    output: Any, value: Any, expected_model: type[BaseModel]
):
    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)

    assert type(list.__getitem__(validated, 0)) is expected_model


@pytest.mark.parametrize(
    "output,value,inner_type",
    [
        (
            list[ListBranchTypedDict] | list[TupleBranchTypedDict],
            [{"items": [1]}],
            list,
        ),
        (
            list[TupleBranchTypedDict] | list[ListBranchTypedDict],
            [{"items": [1]}],
            list,
        ),
        (
            list[ListBranchTypedDict] | list[TupleBranchTypedDict],
            [{"items": (1,)}],
            tuple,
        ),
        (
            list[LeftBranchTypedDict] | list[RightBranchTypedDict],
            [{"right": (1,)}],
            tuple,
        ),
    ],
)
def test_same_container_typed_dict_unions_follow_shape_and_nested_runtime_types(
    output: Any, value: Any, inner_type: type[Any]
):
    validated = _compile_output_validator(TypeAdapter(output)).validate_python(value)
    item = list.__getitem__(validated, 0)

    assert type(item) is dict
    key = "items" if dict.__contains__(item, "items") else "right"
    assert type(dict.__getitem__(item, key)) is inner_type


def test_same_container_union_still_audits_the_selected_nested_model_branch():
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(list[ReplacingTypedDictEnvelope] | list[int])
        ).validate_python([{"item": {"value": 7}}])


def test_same_container_union_still_rejects_nested_generator_replacement():
    CONTAINER_REPLACEMENT_HOOKS.clear()

    with pytest.raises(ValidationError, match="deque"):
        _compile_output_validator(
            TypeAdapter(list[GeneratorReplacingDequeEnvelope] | list[int])
        ).validate_python([{"items": [{"value": 7}]}])

    assert CONTAINER_REPLACEMENT_HOOKS == []


@pytest.mark.parametrize(
    "output",
    [UntaggedTypedDictEnvelope, ReversedUntaggedTypedDictEnvelope],
)
def test_literal_union_branch_matching_uses_exact_values_not_only_types(output: Any):
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(
            {"item": {"kind": "collision", "value": 7}}
        )


def test_literal_union_nan_matches_only_the_identical_expected_object():
    nan = get_args(NaNLiteral)[0]
    assert type(nan) is float and math.isnan(nan)

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(NaNLiteralEnvelope)).validate_python(
            {"item": {"kind": nan, "value": 7}}
        )

    with pytest.raises(ValidationError, match="literal"):
        _compile_output_validator(TypeAdapter(NaNLiteralEnvelope)).validate_python(
            {"item": {"kind": float("nan"), "value": 7}}
        )


@pytest.mark.parametrize(
    "output",
    [TaggedTypedDictEnvelope, ReversedTaggedTypedDictEnvelope],
)
def test_tagged_typed_dict_union_audits_only_the_discriminated_branch(output: Any):
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(
            {"item": {"kind": "collision", "value": 7}}
        )


def test_tagged_union_alias_path_storage_fails_closed_after_replacement():
    with pytest.raises(ValidationError, match="tagged union storage"):
        _compile_output_validator(
            TypeAdapter(AliasPathTaggedTypedDictEnvelope)
        ).validate_python({"item": {"tag": "collision", "value": 7}})


@pytest.mark.parametrize(
    "output",
    [TaggedModelEnvelope, ReversedTaggedModelEnvelope],
)
def test_tagged_model_union_audits_only_the_discriminated_branch(output: Any):
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(output)).validate_python(
            {"item": {"kind": "collision", "value": 7}}
        )


def test_tagged_union_fails_closed_on_hostile_mapping_storage_without_hooks():
    TAGGED_STORAGE_HOOKS.clear()

    with pytest.raises(ValidationError, match="tagged union"):
        _compile_output_validator(
            TypeAdapter(HostileTaggedTypedDictEnvelope)
        ).validate_python({"item": {"kind": "collision", "value": 7}})

    assert TAGGED_STORAGE_HOOKS == []


def test_tagged_union_reads_hostile_model_storage_without_hooks():
    TAGGED_STORAGE_HOOKS.clear()

    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(
            TypeAdapter(HostileTaggedModelEnvelope)
        ).validate_python({"item": {"kind": "collision", "value": 7}})

    assert TAGGED_STORAGE_HOOKS == []


def test_tagged_dataclass_union_reads_slots_and_frozen_storage():
    validated = _compile_output_validator(TypeAdapter(TaggedDataclass)).validate_python(
        {"kind": "safe", "value": 7}
    )

    assert type(validated) is SafeTaggedDataclass
    assert validated.value == 7


def test_tagged_dataclass_union_bypasses_application_storage_hooks():
    DATACLASS_STORAGE_HOOKS.clear()

    validated = _compile_output_validator(
        TypeAdapter(HostileTaggedDataclassEnvelope)
    ).validate_python({"item": {"kind": "safe", "value": 7}})

    assert type(validated.item) is HostileSafeTaggedDataclass
    assert object.__getattribute__(validated.item, "value") == 7
    assert DATACLASS_STORAGE_HOOKS == []


def test_dataclass_audit_bypasses_shadowed_dict_property():
    DATACLASS_STORAGE_HOOKS.clear()

    validated = _compile_output_validator(
        TypeAdapter(ShadowedDictDataclassEnvelope)
    ).validate_python({"item": {"value": 7}})

    assert type(validated.item) is ShadowedDictSlottedDataclass
    assert object.__getattribute__(validated.item, "value") == 7
    assert DATACLASS_STORAGE_HOOKS == []


def test_http_serializes_slotted_dataclass_with_shadowed_dict_property(
    monkeypatch: pytest.MonkeyPatch,
):
    DATACLASS_STORAGE_HOOKS.clear()
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")
    summon = _direct_summon(
        ShadowedDictDataclassEnvelope,
        {"item": {"value": 7}},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 200
    assert response.json() == {"item": {"value": 7}}
    assert DATACLASS_STORAGE_HOOKS == []


def test_tagged_dataclass_union_audits_the_selected_collision_branch():
    with pytest.raises(ValidationError, match="wireValue"):
        _compile_output_validator(TypeAdapter(TaggedDataclass)).validate_python(
            {"kind": "collision", "item": {"value": 7}}
        )


def test_runtime_and_http_preserve_valid_tagged_dataclass_output(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")
    summon = _direct_summon(TaggedDataclass, {"kind": "safe", "value": 7})

    result = asyncio.run(Runtime(model="test").call(summon.endpoints[0], {"value": 7}))
    assert result == {"operation": {"kind": "safe", "value": 7}}

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 200
    assert response.json() == {"operation": {"kind": "safe", "value": 7}}


def test_runtime_and_http_reject_tagged_dataclass_collision_branch(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SUMMONPOT_MODEL", "test")
    summon = _direct_summon(
        TaggedDataclass,
        {"kind": "collision", "item": {"value": 7}},
    )

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(Runtime(model="test").call(summon.endpoints[0], {"value": 7}))

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert "wireValue" not in response.text


@pytest.mark.parametrize(
    "output",
    [
        TaggedTypedDictEnvelope,
        ReversedTaggedTypedDictEnvelope,
        TaggedModelEnvelope,
        ReversedTaggedModelEnvelope,
    ],
)
def test_runtime_and_http_reject_tagged_union_selected_branch_collision(output: Any):
    result = {"item": {"kind": "collision", "value": 7}}
    summon = _direct_summon(output, result)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert "wireValue" not in response.text


def test_runtime_rejects_generator_replacement_before_iteration():
    CONTAINER_REPLACEMENT_HOOKS.clear()
    summon = _direct_summon(GeneratorReplacingDequeEnvelope, {"items": [{"value": 7}]})

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    assert CONTAINER_REPLACEMENT_HOOKS == []


def test_http_rejects_generator_replacement_before_serialization_or_iteration():
    CONTAINER_REPLACEMENT_HOOKS.clear()
    summon = _direct_summon(GeneratorReplacingDequeEnvelope, {"items": [{"value": 7}]})

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert "wireValue" not in response.text
    assert CONTAINER_REPLACEMENT_HOOKS == []


def test_http_rejects_parent_validator_nested_deque_collision():
    summon = _direct_summon(
        MutatingDequeEnvelope,
        {"items": [{"value": 7}]},
    )

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert "wireValue" not in response.text


def test_http_emits_noncolliding_deque_extra_once():
    response = TestClient(
        build_app(
            _direct_summon(
                SafeMutatingDequeEnvelope,
                {"items": [{"value": 7}]},
            )
        )
    ).post("/output", json={"value": 7})

    assert response.status_code == 200
    assert response.json() == {"items": [{"wireValue": 7, "note": "safe"}]}
    assert response.text.count('"wireValue"') == 1
    assert response.text.count('"note"') == 1


def test_http_rejects_deque_subclass_without_calling_hooks():
    DEQUE_AUDIT_HOOKS.clear()
    summon = _direct_summon(
        HostileMutatingDequeEnvelope,
        {"items": [{"value": 7}]},
    )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert DEQUE_AUDIT_HOOKS == []


@pytest.mark.parametrize(
    "output,result",
    [
        (MutatingTypedDictEnvelope, {"item": {"value": 7}}),
        (MutatingFrozenSetEnvelope, {"items": [{"value": 7}]}),
    ],
)
def test_http_rejects_parent_validator_nested_output_collision(
    output: Any, result: Any
):
    summon = _direct_summon(output, result)

    with pytest.raises(_OperationOutputError, match="invalid declared output"):
        asyncio.run(
            Runtime(model="invalid:no-model").call(summon.endpoints[0], {"value": 7})
        )

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert "wireValue" not in response.text


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


def test_safe_namespaces_do_not_bypass_fail_closed_runtime_admission():
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

    with pytest.raises(TypeError, match="cannot enforce the declared call bound"):

        @summon("/output")
        def endpoint(
            request: Request,
            one=Required(first_contract, calls=Exactly(2)),
            two=Required(second_contract, calls=Exactly(1)),
        ) -> SafeAliasesOutput:
            """Keep safe namespaces within supported runtime contracts."""
            ...

    assert summon.endpoints == []


def test_agent_endpoint_output_rejects_alias_shadowing_before_http_serialization():
    summon = Summon("agent-output-namespace")
    summon._runtime = Runtime(
        model=TestModel(custom_output_args={"wireValue": 1, "value": 99})
    )

    @summon("/agent-output")
    def endpoint(request: Request) -> AliasedExtraOutput:
        """Return one namespace-safe agent result."""
        ...

    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/agent-output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"wireValue"') == 0


def test_agent_endpoint_output_preserves_noncolliding_extras():
    summon = Summon("agent-output-namespace-safe")
    summon._runtime = Runtime(
        model=TestModel(custom_output_args={"value": 1, "note": "safe"})
    )

    @summon("/agent-output")
    def endpoint(request: Request) -> AliasedExtraOutput:
        """Return one namespace-safe agent result."""
        ...

    response = TestClient(build_app(summon)).post("/agent-output", json={"value": 7})

    assert response.status_code == 200, response.text
    assert response.json() == {"wireValue": 1, "note": "safe"}


def test_missing_required_typed_dict_field_cannot_disable_collision_audit():
    class RequiredOutput(TypedDict):
        alpha: Annotated[int, Field(serialization_alias="alphaWire")]
        beta: int

    RequiredOutput.__pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[attr-defined]

    class Envelope(BaseModel):
        item: RequiredOutput

        @model_validator(mode="after")
        def replace_item(self) -> "Envelope":
            self.item = {"alpha": 1, "alphaWire": 99}  # type: ignore[assignment,typeddict-unknown-key]
            return self

    validator = _compile_output_validator(TypeAdapter(Envelope))
    with pytest.raises(ValidationError, match=r"missing required fields.*beta"):
        validator.validate_python({"item": {"alpha": 1, "beta": 2}})

    result = {"item": {"alpha": 1, "beta": 2}}
    direct = _direct_summon(Envelope, result)
    with pytest.raises(_OperationOutputError):
        asyncio.run(direct._runtime.call(direct.endpoints[0], {"value": 7}))

    http = _direct_summon(Envelope, result)
    response = TestClient(build_app(http), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )
    assert response.status_code == 500
    assert response.text.count('"alphaWire"') == 0


def test_runtime_model_in_untyped_extra_cannot_own_duplicate_emitted_keys():
    class SelfCollidingModel(BaseModel):
        value: int

        @computed_field(alias="value")
        @property
        def doubled(self) -> int:
            return self.value * 2

    class HolderModel(BaseModel):
        model_config = ConfigDict(extra="allow")
        value: int

    result = HolderModel.model_validate(
        {"value": 1, "inner": SelfCollidingModel(value=5)}
    )
    summon = _direct_summon(HolderModel, result)
    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert response.status_code == 500
    assert response.text.count('"value"') == 0


def test_runtime_model_in_untyped_extra_preserves_unique_emitted_keys():
    class SafeComputedModel(BaseModel):
        value: int

        @computed_field(alias="doubledValue")
        @property
        def doubled(self) -> int:
            return self.value * 2

    class HolderModel(BaseModel):
        model_config = ConfigDict(extra="allow")
        value: int

    result = HolderModel.model_validate(
        {"value": 1, "inner": SafeComputedModel(value=5)}
    )
    summon = _direct_summon(HolderModel, result)
    response = TestClient(build_app(summon)).post("/output", json={"value": 7})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "value": 1,
        "inner": {"value": 5, "doubledValue": 10},
    }


@pytest.mark.parametrize("colliding", [True, False])
def test_runtime_model_namespace_audit_bypasses_application_metaclass(
    colliding: bool,
):
    hooks: list[str] = []

    class HostileModelMeta(type(BaseModel)):
        def __getattribute__(cls, name: str) -> Any:
            if name in {"model_fields", "model_computed_fields"}:
                hooks.append(name)
                return {}
            return super().__getattribute__(name)

    class AliasedModel(BaseModel, metaclass=HostileModelMeta):
        model_config = ConfigDict(extra="allow")
        value: int = Field(serialization_alias="wire")

    class HolderModel(BaseModel):
        model_config = ConfigDict(extra="allow")
        value: int

    extra_name = "wire" if colliding else "note"
    inner = AliasedModel.model_validate({"value": 1, extra_name: 99})
    result = HolderModel.model_validate({"value": 2, "inner": inner})
    hooks.clear()
    summon = _direct_summon(HolderModel, result)
    response = TestClient(build_app(summon), raise_server_exceptions=False).post(
        "/output", json={"value": 7}
    )

    assert hooks == []
    if colliding:
        assert response.status_code == 500
        assert response.text.count('"wire"') == 0
    else:
        assert response.status_code == 200, response.text
        assert response.json() == {
            "value": 2,
            "inner": {"wire": 1, "note": 99},
        }
