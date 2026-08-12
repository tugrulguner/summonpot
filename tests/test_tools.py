"""Tests for deterministic tool and capability construction."""

from __future__ import annotations

import asyncio
from typing import Any

from summonpot.tools import build_tool_from_func, tool


def test_tool_decorator_uses_function_metadata_and_defaults():
    @tool()
    def transform(
        values: list[int], options: dict[str, bool] | None = None
    ) -> tuple[int, ...]:
        """Transform typed values."""
        return tuple(values) if options is None else tuple(reversed(values))

    assert transform.name == "transform"
    assert transform.description == "Transform typed values."
    assert [parameter.name for parameter in transform.parameters] == [
        "values",
        "options",
    ]
    assert transform.parameters[0].type_annotation == "list[int]"
    assert transform.parameters[0].required is True
    assert transform.parameters[1].type_annotation == "dict[str, bool] | None"
    assert transform.parameters[1].required is False
    assert transform.parameters[1].default is None


def test_build_tool_skips_method_receiver_from_schema():
    def combine(self: Any, value: int, enabled: bool = True) -> dict[str, Any]:
        """Combine exact inputs."""
        return {"value": value, "enabled": enabled}

    definition = build_tool_from_func(combine)

    assert [parameter.name for parameter in definition.parameters] == [
        "value",
        "enabled",
    ]


def test_tooldef_executes_sync_function():
    def combine(value: int, enabled: bool = True) -> dict[str, Any]:
        return {"value": value, "enabled": enabled}

    definition = build_tool_from_func(combine)

    assert asyncio.run(definition.call(value=3)) == {"value": 3, "enabled": True}


def test_tooldef_executes_async_function():
    async def fetch(identifier: str) -> str:
        """Fetch one record."""
        return f"record:{identifier}"

    definition = build_tool_from_func(fetch)

    assert asyncio.run(definition.call(identifier="123")) == "record:123"


def test_unannotated_parameters_default_to_string_type():
    def lookup(value):
        return value

    definition = build_tool_from_func(lookup)

    assert definition.parameters[0].type_annotation == "str"
