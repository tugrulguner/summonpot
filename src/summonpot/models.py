"""Data models for summonpot."""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from summonpot.contracts import CallBounds, Operation


@dataclass
class ParamDef:
    """A single parameter of an endpoint or tool."""

    name: str
    type_annotation: str = "str"
    description: str = ""
    required: bool = True
    default: Any = None
    # The resolved annotation object. `type_annotation` is a display string and
    # cannot round-trip a union or a generic's element type, so the HTTP layer
    # builds its request model from this instead.
    annotation: Any = None


@dataclass
class ToolDef:
    """A tool registered with summonpot."""

    name: str
    description: str
    parameters: list[ParamDef] = field(default_factory=list)
    fn: Any = None  # the callable
    required: bool = False
    # The typed contract and resolved call bounds. Registration compiles these into
    # a private immutable execution plan; this mutable object remains inspection data.
    contract: Operation | None = None
    bounds: CallBounds | None = None

    async def call(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the tool with the given arguments.

        Synchronous capabilities run in a worker thread so that one slow operation
        cannot stall every other request sharing the event loop.
        """
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(*args, **kwargs)

        result = await asyncio.to_thread(self.fn, *args, **kwargs)
        # A callable object whose __call__ is async is not caught by
        # iscoroutinefunction; calling it merely builds the coroutine, so it still
        # has to be awaited rather than handed back to the model as a result.
        if inspect.isawaitable(result):
            return await result
        return result


PATH_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def path_placeholders(path: str) -> list[str]:
    """The `{name}` placeholders in a route template, in order, exactly as written.

    Duplicates are kept: a template naming the same placeholder twice is a
    declaration error, and collapsing them here would hide it.

    Nothing is normalised either, for the same reason. Stripping the text
    inside the braces made `/items/{ item_id }` *pass* registration as
    `item_id`, while the route handed to Starlette still carried the
    unstripped placeholder -- so the declaration and the served route
    disagreed about the name, and the mismatch surfaced only at request time.
    Returning the raw text lets the caller reject it as the malformed
    declaration it is.
    """
    return [match.group(1) for match in PATH_PLACEHOLDER.finditer(path)]


@dataclass
class EndpointDef:
    """A registered endpoint summoned behind a route."""

    path: str
    name: str
    description: str  # docstring = system prompt
    parameters: list[ParamDef] = field(default_factory=list)
    return_type: str = "str"
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None
    tools: list[ToolDef] = field(default_factory=list)
    stream: bool = False
    model: str | None = None
    method: str = "POST"
    path_parameter_names: tuple[str, ...] = ()
    """Declared parameters bound from the URL, not the body. Set at registration."""
