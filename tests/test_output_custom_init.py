"""Custom constructors must not re-enter unhardened class validators."""

from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError, model_validator

from summonpot import Exactly, FromRequest, Operation, Required, Summon
from summonpot._output_validation import _compile_output_validator


class Child(BaseModel):
    x: int


class Outer(BaseModel):
    child: Child

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


@pytest.mark.parametrize("mapping", [False, True])
@pytest.mark.parametrize("invalid", [False, True])
def test_custom_init_output_rejected_before_operation(mapping: bool, invalid: bool):
    child = Child.model_construct(x="bad" if invalid else 1)
    output = {"child": child} if mapping else Outer.model_construct(child=child)
    called = []

    def operation(x: int) -> Outer:
        called.append(x)
        return output  # type: ignore[return-value]

    summon = Summon("custom-init")
    with pytest.raises(TypeError, match=r"Outer.*custom __init__.*model validators"):

        @summon("/custom-init")
        def endpoint(
            request: Child,
            result=Required(
                Operation(operation, bind={"x": FromRequest("x")}, output=Outer),
                calls=Exactly(1),
            ),
        ) -> Outer:
            """Reject unsupported constructors before accepting traffic."""
            ...

    assert called == []
    assert summon.endpoints == []


class Envelope(BaseModel):
    items: list[Outer]


class Recursive(BaseModel):
    children: list["Recursive"] = []
    item: Outer | None = None


class Inherited(Outer):
    pass


@pytest.mark.parametrize(
    "output_type", [Envelope, Recursive, Inherited, list[Outer], Outer | int]
)
def test_custom_init_rejected_through_nested_recursive_and_union_schemas(
    output_type: Any,
):
    with pytest.raises(TypeError, match=r"custom __init__.*model validators"):
        _compile_output_validator(TypeAdapter(output_type))


def test_rejection_preserves_original_constructor_transformations():
    class Transforming(BaseModel):
        x: int

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(x=kwargs["x"] + 1)

    schema = Transforming.__pydantic_core_schema__
    validator = Transforming.__pydantic_validator__
    with pytest.raises(TypeError, match=r"Transforming.*custom __init__"):
        _compile_output_validator(TypeAdapter(Transforming))
    assert Transforming.__pydantic_core_schema__ is schema
    assert Transforming.__pydantic_validator__ is validator
    assert Transforming.model_validate({"x": 1}).x == 2


@pytest.mark.parametrize("mapping", [False, True])
def test_plain_models_and_model_validators_remain_supported(mapping: bool):
    class Supported(BaseModel):
        child: Child

        @model_validator(mode="before")
        @classmethod
        def transform(cls, value: Any) -> Any:
            if isinstance(value, dict) and "external" in value:
                return {"child": value["external"]}
            return value

    validator = _compile_output_validator(TypeAdapter(Supported))
    valid = Child(x=1)
    value = {"external": valid} if mapping else Supported.model_construct(child=valid)
    assert validator.validate_python(value).child.x == 1
    bad = Child.model_construct(x="bad")
    value = {"external": bad} if mapping else Supported.model_construct(child=bad)
    with pytest.raises(ValidationError):
        validator.validate_python(value)
    # Compilation must not harden the application's original class validator.
    assert Child.model_validate(bad) is bad


def test_any_does_not_reject_or_inspect_custom_init_runtime_values():
    value = Outer.model_construct(child=Child.model_construct(x="bad"))
    assert _compile_output_validator(TypeAdapter(Any)).validate_python(value) is value
