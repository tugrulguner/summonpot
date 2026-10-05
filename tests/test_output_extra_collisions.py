"""Declared output fields and allowed extras share one emitted namespace."""

from typing import Any

import pytest
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from summonpot._output_validation import _compile_output_validator


class Collision(BaseModel):
    model_config = ConfigDict(extra="allow")
    x: int = Field(alias="external")


def test_extra_cannot_shadow_a_canonical_declared_field():
    original = Collision.model_construct(external=1, x="hostile")
    fields = original.__dict__.copy()
    assert original.__pydantic_extra__ is not None
    extras = original.__pydantic_extra__.copy()

    with pytest.raises(ValidationError, match=r"shadow.*'x'"):
        _compile_output_validator(TypeAdapter(Collision)).validate_python(original)

    assert original.__dict__ == fields
    assert original.__pydantic_extra__ == extras


def test_invalid_declared_field_is_not_laundered_by_a_colliding_extra():
    original = Collision.model_construct(external="bad", x=7)

    with pytest.raises(ValidationError, match="int"):
        _compile_output_validator(TypeAdapter(Collision)).validate_python(original)

    assert original.x == "bad"
    assert original.__pydantic_extra__ == {"x": 7}


def test_noncolliding_extra_remains_supported():
    original = Collision.model_construct(external=1, note="safe")

    validated = _compile_output_validator(TypeAdapter(Collision)).validate_python(
        original
    )

    assert validated.x == 1
    assert validated.__pydantic_extra__ == {"note": "safe"}
    assert original.__pydantic_extra__ == {"note": "safe"}


class TypedCollision(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, int] = Field(init=False)  # type: ignore[reportIncompatibleVariableOverride]
    x: str = Field(alias="external")


@pytest.mark.parametrize("extra", [7, "bad"])
def test_typed_colliding_extra_is_rejected_without_mutation(extra: Any):
    original = TypedCollision.model_construct(external="valid field", x=extra)

    with pytest.raises(ValidationError):
        _compile_output_validator(TypeAdapter(TypedCollision)).validate_python(original)

    assert original.x == "valid field"
    assert original.__pydantic_extra__ == {"x": extra}


@pytest.mark.parametrize("extra,valid", [(7, True), ("bad", False)])
def test_noncolliding_typed_extra_is_still_validated(extra: Any, valid: bool):
    original = TypedCollision.model_construct(external="valid field", note=extra)
    call = _compile_output_validator(TypeAdapter(TypedCollision)).validate_python

    if valid:
        assert call(original).__pydantic_extra__ == {"note": 7}
    else:
        with pytest.raises(ValidationError):
            call(original)


@pytest.mark.parametrize("instance", [False, True])
def test_nested_alias_collision_is_rejected(instance: bool):
    class Envelope(BaseModel):
        item: Collision = Field(alias="payload")

    item = Collision.model_validate({"external": 1, "x": "extra"})
    original = Envelope.model_construct(item=item) if instance else {"payload": item}

    with pytest.raises(ValidationError, match=r"shadow.*'x'"):
        _compile_output_validator(TypeAdapter(Envelope)).validate_python(original)

    assert item.x == 1
    assert item.__pydantic_extra__ == {"x": "extra"}


@pytest.mark.parametrize("invalid", [False, True])
def test_typed_noncolliding_extra_revalidates_nested_models(invalid: bool):
    class NestedExtras(BaseModel):
        model_config = ConfigDict(extra="allow")
        __pydantic_extra__: dict[str, Collision]  # type: ignore[reportIncompatibleVariableOverride]
        x: Any = Field(alias="external")

    extra = Collision.model_construct(external="bad" if invalid else 2, note="safe")
    original = NestedExtras.model_construct(external=1, nested=extra)
    call = _compile_output_validator(TypeAdapter(NestedExtras)).validate_python

    if invalid:
        with pytest.raises(ValidationError):
            call(original)
    else:
        result = call(original)
        assert result.x == 1
        assert result.__pydantic_extra__["nested"] == extra
    assert original.__pydantic_extra__["nested"] is extra


def test_recursive_collision_context_resets_after_failure():
    class Recursive(Collision):
        children: list["Recursive"] = Field(default_factory=list)

    validator = _compile_output_validator(TypeAdapter(Recursive))
    with pytest.raises(ValidationError, match=r"shadow.*'x'"):
        validator.validate_python(Recursive.model_construct(external=1, x="failed"))

    child = Recursive.model_construct(external=2, note="child")
    original = Recursive.model_construct(external=1, note="parent", children=[child])
    result = validator.validate_python(original)
    assert result.__pydantic_extra__ == {"note": "parent"}
    assert result.children[0].__pydantic_extra__ == {"note": "child"}


def test_model_validators_see_defined_noncolliding_extra_views():
    seen = []

    class Checked(Collision):
        @model_validator(mode="before")
        @classmethod
        def before(cls, value: Any):
            seen.append(("before", value.copy()))
            return value

        @model_validator(mode="after")
        def after(self):
            seen.append(("after", self.x, (self.__pydantic_extra__ or {}).copy()))
            return self

    original = Checked.model_construct(external=1, note="ordinary")
    result = _compile_output_validator(TypeAdapter(Checked)).validate_python(original)

    assert result == original
    assert seen == [
        ("before", {"x": 1, "note": "ordinary"}),
        ("after", 1, {"note": "ordinary"}),
    ]
