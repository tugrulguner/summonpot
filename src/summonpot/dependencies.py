"""Declarative deterministic capabilities for agentic endpoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Dependency:
    """An exact operation exposed to an endpoint agent."""

    operation: Callable[..., Any]
    required: bool = False


def Depends(operation: Callable[..., Any]) -> Dependency:
    """Expose an operation the agent may call."""
    return Dependency(operation=operation)


def Required(operation: Callable[..., Any]) -> Dependency:
    """Expose an operation that must run before successful output."""
    return Dependency(operation=operation, required=True)
