"""Narrow repeated-stage admission and backwards-compatible result bindings."""

from typing import Literal

import pytest
from pydantic import BaseModel

from summonpot import (
    AgentChoice,
    Between,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)


class Request(BaseModel):
    key: str


class Snapshot(BaseModel):
    key: str


class Report(BaseModel):
    key: str


def declare(
    *,
    selector="final",
    bounds=None,
    reverse=False,
    ordered=False,
    extra=False,
    terminal_choice=False,
    same_output=False,
):
    def inspect(key: str, check: Literal["stock", "prices"]) -> Snapshot:
        return Snapshot(key=key)

    def finalize(key: str) -> Report:
        return Report(key=key)

    first = Operation(
        inspect,
        bind={"key": FromRequest("key"), "check": AgentChoice()},
        output=Snapshot,
    )
    second = Operation(
        finalize,
        bind={
            "key": AgentChoice()
            if terminal_choice
            else FromResult(first, "key", invocation=selector)
        },
        output=Snapshot if same_output else Report,
        after=(first,) if ordered else (),
    )
    app = Summon("admission")
    producer_marker = Required(first, calls=bounds or Between(1, 3))
    terminal_marker = Required(second, calls=Exactly(1))
    if reverse:

        @app("/audit")
        def reversed_endpoint(
            request: Request, terminal=terminal_marker, checks=producer_marker
        ) -> Report:
            """Inspect and return a final report."""
            ...
    elif extra:

        def additional(key: str) -> str:
            return key

        third = Operation(additional, bind={"key": FromRequest("key")}, output=str)

        @app("/audit")
        def expanded(
            request: Request,
            checks=producer_marker,
            terminal=terminal_marker,
            other=Required(third, calls=Exactly(1)),
        ) -> Report:
            """Inspect and return a final report."""
            ...
    else:

        @app("/audit")
        def endpoint(
            request: Request, checks=producer_marker, terminal=terminal_marker
        ) -> Report:
            """Inspect and return a final report."""
            ...

    return app


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("ordered", [False, True])
def test_registration_is_identity_ordered_not_declaration_order(reverse, ordered):
    assert len(declare(reverse=reverse, ordered=ordered).endpoints) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"selector": None},
        {"bounds": Exactly(1)},
        {"extra": True},
        {"terminal_choice": True},
        {"same_output": True},
    ],
)
def test_unsupported_combinations_reject_at_registration(kwargs):
    with pytest.raises(TypeError):
        declare(**kwargs)


def test_selector_rejects_string_subclasses():
    class Selector(str):
        pass

    with pytest.raises(ValueError):
        FromResult(Operation(lambda: None), "key", invocation=Selector("final"))
