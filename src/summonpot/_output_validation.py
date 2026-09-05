"""Compile private operation validators without serializing application values.

This relies on the tested Pydantic 2.13.5 / pydantic-core 2.46.5 schema
contract and the private ``_use_prebuilt`` compiler option. Dependency upgrades
must run the adversarial regression suite: allowing prebuilt validators silently
restores the model class's default (non-revalidating) instance behavior. Never
fall back to the original adapter if compilation fails.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, cast

from pydantic import BaseModel, TypeAdapter
from pydantic_core import SchemaValidator, core_schema


def _input_kind(value: Any) -> str:
    return (
        "instance"
        if isinstance(value, BaseModel)
        or (is_dataclass(value) and not isinstance(value, type))
        else "input"
    )


def _revalidating_schema(node: Any) -> Any:
    """Copy schema containers, retaining classes, hooks and definition references.

    Model instances hold canonical field names; mappings must retain their
    declared alias policy, even when nested inside a constructed instance.
    Branch locally at each model node rather than overriding validation flags
    globally. Any schemas deliberately remain Any: do not traverse runtime data.
    """
    if isinstance(node, dict):
        is_schema = isinstance(node.get("type"), str)
        result = {
            key: value
            if is_schema and key in {"default", "metadata", "config", "serialization"}
            else _revalidating_schema(value)
            for key, value in node.items()
        }
        if (
            node.get("type") not in ("model", "dataclass")
            or "cls" not in node
            or "schema" not in node
        ):
            return result
        result["revalidate_instances"] = "always"
        config = {**result.get("config", {}), "revalidate_instances": "always"}
        result["config"] = config
        reference = result.pop("ref", None)
        canonical = {
            **result,
            "config": {
                **config,
                "validate_by_alias": False,
                "validate_by_name": True,
            },
        }
        branch: dict[str, Any] = {
            "type": "tagged-union",
            "choices": {"instance": canonical, "input": result},
            "discriminator": _input_kind,
        }
        if reference is not None:
            branch["ref"] = reference
        return branch
    if isinstance(node, list):
        return [_revalidating_schema(value) for value in node]
    if isinstance(node, tuple):
        return tuple(_revalidating_schema(value) for value in node)
    return node


def _compile_output_validator(adapter: TypeAdapter[Any]) -> SchemaValidator:
    """Compile once at registration without modifying class-owned schemas."""
    schema = cast(core_schema.CoreSchema, _revalidating_schema(adapter.core_schema))
    # REQUIRED: prebuilt class validators bypass our nested model branches and
    # revalidation policy. This private flag is covered by nested/recursive tests.
    return SchemaValidator(schema, _use_prebuilt=False)
