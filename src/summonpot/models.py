"""Data models for summonpot."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class ParamDef:
    """A single parameter of an endpoint or tool."""

    name: str
    type_annotation: str = "str"
    description: str = ""
    required: bool = True
    default: Any = None


@dataclass
class ToolDef:
    """A tool registered with summonpot."""

    name: str
    description: str
    parameters: list[ParamDef] = field(default_factory=list)
    fn: Any = None  # the callable

    async def call(self, **kwargs: Any) -> Any:
        """Execute the tool with the given arguments."""
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(**kwargs)
        return self.fn(**kwargs)


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
