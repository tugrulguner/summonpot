"""Canonical model storage and allowed extras are independent namespaces."""

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


@pytest.mark.parametrize("field,extra", [("bad", 7), (1, "allowed extra"), (1, 7)])
def test_collision_keeps_declared_fields_and_extras_separate(field: Any, extra: Any):
    original = Collision.model_construct(external=field, x=extra)
    fields = original.__dict__.copy()
    assert original.__pydantic_extra__ is not None
    extras = original.__pydantic_extra__.copy()
    validator = _compile_output_validator(TypeAdapter(Collision))
    if field == "bad":
        with pytest.raises(ValidationError):
            validator.validate_python(original)
    else:
        validated = validator.validate_python(original)
        assert validated.x == field
        assert validated.__pydantic_extra__ == extras
        assert validated == original
    assert original.__dict__ == fields
    assert original.__pydantic_extra__ == extras


class TypedCollision(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, int] = Field(init=False)  # type: ignore[reportIncompatibleVariableOverride]
    x: str = Field(alias="external")


@pytest.mark.parametrize("extra", [7, "bad"])
def test_collision_enforces_typed_extras(extra: Any):
    original = TypedCollision.model_construct(external="valid field", x=extra)
    validator = _compile_output_validator(TypeAdapter(TypedCollision))
    if extra == "bad":
        with pytest.raises(ValidationError):
            validator.validate_python(original)
    else:
        validated = validator.validate_python(original)
        assert validated.x == "valid field"
        assert validated.__pydantic_extra__ == {"x": 7}
    assert original.x == "valid field"
    assert original.__pydantic_extra__ == {"x": extra}


@pytest.mark.parametrize("instance", [False, True])
def test_nested_alias_collision_preserves_namespaces(instance: bool):
    class Envelope(BaseModel):
        item: Collision = Field(alias="payload")

    item = Collision.model_validate({"external": 1, "x": "extra"})
    original = Envelope.model_construct(item=item) if instance else {"payload": item}
    result = _compile_output_validator(TypeAdapter(Envelope)).validate_python(original)
    assert result.item.x == 1
    assert result.item.__pydantic_extra__ == {"x": "extra"}
    assert item.x == 1
    assert item.__pydantic_extra__ == {"x": "extra"}


def test_after_validator_sees_preserved_collision():
    class Checked(Collision):
        @model_validator(mode="after")
        def check_namespaces(self):
            assert self.x == 1
            assert self.__pydantic_extra__ == {"x": "extra"}
            return self

    original = Checked.model_construct(external=1, x="extra")
    result = _compile_output_validator(TypeAdapter(Checked)).validate_python(original)
    assert result == original


@pytest.mark.parametrize("invalid", [False, True])
def test_typed_collision_extra_revalidates_nested_models(invalid: bool):
    class NestedExtras(BaseModel):
        model_config = ConfigDict(extra="allow")
        __pydantic_extra__: dict[str, Collision]  # type: ignore[reportIncompatibleVariableOverride]
        x: Any = Field(alias="external")

    extra = Collision.model_construct(external="bad" if invalid else 2, x="extra")
    original = NestedExtras.model_construct(external=1, x=extra)
    validator = _compile_output_validator(TypeAdapter(NestedExtras))
    if invalid:
        with pytest.raises(ValidationError):
            validator.validate_python(original)
    else:
        result = validator.validate_python(original)
        assert result.x == 1
        assert result.__pydantic_extra__["x"] == extra
    assert original.x == 1
    assert original.__pydantic_extra__["x"] is extra


def test_recursive_collision_context_is_local_and_resets_after_failure():
    class Recursive(Collision):
        children: list["Recursive"] = Field(default_factory=list)

    child = Recursive.model_construct(external=2, x="child")
    original = Recursive.model_construct(external=1, x="parent", children=[child])
    validator = _compile_output_validator(TypeAdapter(Recursive))
    with pytest.raises(ValidationError):
        validator.validate_python(Recursive.model_construct(external="bad", x="failed"))
    result = validator.validate_python(original)
    assert result == original
    assert result.__pydantic_extra__ == {"x": "parent"}
    assert result.children[0].__pydantic_extra__ == {"x": "child"}


def test_before_and_wrap_validators_see_defined_collision_views():
    seen = []

    class Checked(Collision):
        @model_validator(mode="before")
        @classmethod
        def before(cls, value: Any):
            seen.append(("before", value.copy()))
            return value

        @model_validator(mode="wrap")
        @classmethod
        def wrap(cls, value: Any, handler: Any):
            result = handler(value)
            seen.append(("wrap", result.x, result.__pydantic_extra__.copy()))
            return result

    original = Checked.model_construct(external=1, x="collision", other="ordinary")
    result = _compile_output_validator(TypeAdapter(Checked)).validate_python(original)
    assert result == original
    assert seen == [
        ("before", {"x": 1, "other": "ordinary"}),
        ("wrap", 1, {"x": "collision", "other": "ordinary"}),
    ]
