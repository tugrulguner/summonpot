"""Compile private operation validators without serializing application values.

This relies on the tested Pydantic 2.13.5 / pydantic-core 2.46.5 schema
contract and the private ``_use_prebuilt`` compiler option. Dependency upgrades
must run the adversarial regression suite: allowing prebuilt validators silently
restores the model class's default (non-revalidating) instance behavior. Never
fall back to the original adapter if compilation fails.
"""

from __future__ import annotations

from contextvars import ContextVar
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


def _separate_model_extras(model: dict[str, Any]) -> dict[str, Any]:
    """Keep colliding extras out of core's instance-dict merge.

    Before validators receive canonical fields plus noncolliding extras, just as
    mapping validation does; one mapping cannot represent both namespaces. After
    and outer wrap validators receive the reconstructed model with both intact.
    A per-model ContextVar carries only the detached collision dictionary to the
    model-fields schema. Tokens make recursive/reentrant validation independent.
    """
    pending: ContextVar[tuple[dict[str, Any], bool] | None] = ContextVar(
        "output_extras", default=None
    )
    field_names: set[str] = set()

    def split(value: Any) -> tuple[Any, dict[str, Any]]:
        state = pending.get()
        if state is None:
            return value, {}
        collisions, internal_slot = state
        if internal_slot and isinstance(value, dict):
            value = {
                key: item for key, item in value.items() if key != "__pydantic_extra__"
            }
        return value, collisions

    def join(value: Any) -> Any:
        (fields, extras, fields_set), collisions = value
        return fields, {**(extras or {}), **collisions}, fields_set

    def replace_fields(schema: dict[str, Any]) -> dict[str, Any]:
        if schema.get("type") == "model-fields":
            field_names.update(schema["fields"])
            extra_schema = core_schema.dict_schema(
                keys_schema=schema.get("extras_keys_schema", core_schema.str_schema()),
                values_schema=schema.get("extras_schema", core_schema.any_schema()),
            )
            return cast(
                dict[str, Any],
                core_schema.no_info_after_validator_function(
                    join,
                    core_schema.no_info_before_validator_function(
                        split,
                        core_schema.tuple_positional_schema(
                            [cast(core_schema.CoreSchema, schema), extra_schema]
                        ),
                    ),
                ),
            )
        # Model before/wrap hooks surround model-fields; do not descend into
        # field schemas or reference definitions belonging to other models.
        if "schema" in schema:
            return {**schema, "schema": replace_fields(schema["schema"])}
        return schema

    inner = {**model, "schema": replace_fields(model["schema"])}

    def detach(value: Any, handler: Any) -> Any:
        if not isinstance(value, model["cls"]):
            return handler(value)
        extras = value.__pydantic_extra__ or {}
        collisions = {key: item for key, item in extras.items() if key in field_names}
        # Do not invoke application copy hooks or write to the caller's storage.
        detached = object.__new__(type(value))
        storage = value.__dict__.copy()
        # Pydantic model_construct can place this annotated internal slot in
        # __dict__ as well; it is not a declared field or an additional extra.
        storage.pop("__pydantic_extra__", None)
        object.__setattr__(detached, "__dict__", storage)
        object.__setattr__(
            detached,
            "__pydantic_extra__",
            {key: item for key, item in extras.items() if key not in field_names},
        )
        object.__setattr__(
            detached, "__pydantic_fields_set__", value.__pydantic_fields_set__.copy()
        )
        private = value.__pydantic_private__
        object.__setattr__(
            detached,
            "__pydantic_private__",
            None if private is None else private.copy(),
        )
        token = pending.set((collisions, "__pydantic_extra__" in detached.__dict__))
        try:
            return handler(detached)
        finally:
            pending.reset(token)

    return cast(
        dict[str, Any],
        core_schema.no_info_wrap_validator_function(
            detach, cast(core_schema.CoreSchema, inner)
        ),
    )


def _revalidating_schema(node: Any) -> Any:
    """Copy schema containers, retaining classes, hooks and definition references.

    Model instances hold canonical field names; mappings must retain their
    declared alias policy, even when nested inside a constructed instance.
    Branch locally at each model node rather than overriding validation flags
    globally. Any schemas deliberately remain Any: do not traverse runtime data.
    """
    if isinstance(node, dict):
        if node.get("type") == "model" and node.get("custom_init"):
            # Core invokes custom constructors even with _use_prebuilt=False.
            # A normal super().__init__ call then re-enters the original class
            # validator, bypassing our nested instance revalidation. Disabling
            # custom_init would silently discard mapping-input transformations;
            # reject the unsupported contract at registration instead.
            cls = node["cls"]
            raise TypeError(
                f"Output model {cls.__qualname__!r} uses a custom __init__, which "
                "is unsupported for runtime-enforced operation outputs; use "
                "model validators instead (including for nested models)."
            )
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
        if (
            node.get("type") == "model"
            and config.get("extra_fields_behavior") == "allow"
        ):
            canonical = _separate_model_extras(canonical)
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
