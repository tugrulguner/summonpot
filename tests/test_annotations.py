"""Tests for the shared annotation helpers.

These branches were previously duplicated between summon.py and tools.py, and several
were untested in both copies.
"""

from __future__ import annotations

import inspect
import typing
from typing import Annotated, get_args, get_origin

import pytest
from pydantic import Field, ValidationError, create_model

from summonpot._annotations import get_type_str, safe_get_type_hints, type_name


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (str, "str"),
        (type(None), "None"),
        (list[str], "list[str]"),
        (dict[str, int], "dict[str, int]"),
        (tuple[int, str], "tuple[int, str]"),
        (list[dict[str, int]], "list[dict[str, int]]"),
        (list, "list"),
    ],
)
def test_type_name_renders_generics(annotation, expected):
    assert type_name(annotation) == expected


def test_type_name_falls_back_to_str_for_unnamed_annotations():
    assert type_name(int | None) == "int | None"


def test_get_type_str_prefers_resolved_hints_over_raw_annotations():
    def endpoint(value: list[int]) -> None: ...

    parameters = inspect.signature(endpoint).parameters
    hints = safe_get_type_hints(endpoint)

    assert get_type_str("value", parameters["value"], hints) == "list[int]"


def test_get_type_str_defaults_to_str_when_unannotated():
    def endpoint(value) -> None: ...

    parameters = inspect.signature(endpoint).parameters

    assert get_type_str("value", parameters["value"], {}) == "str"


def test_safe_get_type_hints_resolves_string_annotations():
    def endpoint(value: int) -> str: ...

    assert safe_get_type_hints(endpoint) == {"value": int, "return": str}


def test_safe_get_type_hints_follows_nested_quoted_forward_references():
    """PEP 563 stores `x: "int"` as the source text '"int"', not as 'int'."""

    def endpoint(value): ...

    endpoint.__annotations__ = {"value": '"int"', "return": '"str"'}

    assert safe_get_type_hints(endpoint) == {"value": int, "return": str}


def test_safe_get_type_hints_reports_the_name_that_failed():
    def endpoint(value): ...

    endpoint.__annotations__ = {"value": '"NeverDefined"'}

    # The failing *name* comes back, not the quoted source, so the error reads well.
    assert safe_get_type_hints(endpoint)["value"] == "NeverDefined"


def test_safe_get_type_hints_resolves_forward_references_inside_containers():
    """A quoted reference may sit inside an otherwise resolvable outer type."""

    def endpoint(items): ...

    endpoint.__annotations__ = {"items": 'list["int"]', "return": 'dict[str, "int"]'}

    assert safe_get_type_hints(endpoint) == {
        "items": list[int],
        "return": dict[str, int],
    }


def test_safe_get_type_hints_reports_a_missing_name_nested_in_a_container():
    def endpoint(items): ...

    endpoint.__annotations__ = {"items": 'list["NeverDefined"]'}

    # Just the failing name, not the whole container source.
    assert safe_get_type_hints(endpoint)["items"] == "NeverDefined"


def test_safe_get_type_hints_preserves_annotated_metadata():
    """Annotated carries the parameter's constraints; resolution must not drop them."""

    def endpoint(value): ...

    endpoint.__annotations__ = {"value": Annotated[str, Field(min_length=3)]}

    resolved = safe_get_type_hints(endpoint)["value"]

    assert hasattr(resolved, "__metadata__")


def test_annotated_constraint_still_validates_after_resolution():
    """The metadata must remain functional, not merely present."""

    def endpoint(value): ...

    endpoint.__annotations__ = {"value": Annotated[str, Field(min_length=3)]}
    resolved = safe_get_type_hints(endpoint)["value"]

    # This is how the HTTP layer builds its request model from the resolved type.
    model = create_model("Request", value=(resolved, ...))

    assert model(value="abc").value == "abc"
    with pytest.raises(ValidationError):
        model(value="ab")


def test_annotated_metadata_survives_a_nested_forward_reference():
    """Extras must be kept even when the inner type is a quoted reference."""

    def endpoint(values): ...

    endpoint.__annotations__ = {"values": 'list[Annotated["int", Field(ge=1)]]'}

    resolved = safe_get_type_hints(endpoint)["values"]

    # Compared structurally: two Field(...) calls produce distinct FieldInfo objects.
    (element,) = get_args(resolved)
    assert get_origin(resolved) is list
    assert hasattr(element, "__metadata__")

    model = create_model("Request", values=(resolved, ...))
    assert model(values=[1, 2]).values == [1, 2]
    with pytest.raises(ValidationError):
        model(values=[0])


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (int | None, "int | None"),
        (str | int, "str | int"),
        (dict[str, bool] | None, "dict[str, bool] | None"),
        (list[int] | dict[str, str] | None, "list[int] | dict[str, str] | None"),
        (tuple[int, str] | None, "tuple[int, str] | None"),
    ],
)
def test_type_name_renders_pep604_unions(annotation, expected):
    """Unions must not collapse to '__origin__' on interpreters that expose it."""
    assert type_name(annotation) == expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (typing.Optional[int], "int | None"),
        (typing.Union[int, str], "int | str"),
        (typing.Union[str, int, None], "str | int | None"),
        (typing.Optional[dict[str, bool]], "dict[str, bool] | None"),
    ],
)
def test_type_name_renders_typing_unions(annotation, expected):
    """Legacy typing.Union and typing.Optional must render correctly."""
    assert type_name(annotation) == expected
