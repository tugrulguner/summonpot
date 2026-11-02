"""Admission stays narrow while stage chains compose existing typed dataflow."""

import asyncio
from typing import Any, Literal

import pytest
from test_stage_chains import Prepared, Report, Request, Snapshot, Verified, chain_app

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


@pytest.mark.parametrize("reverse", [False, True])
def test_declaration_order_does_not_change_execution(reverse):
    app, runtime, events, turns = chain_app(reverse=reverse)
    result = asyncio.run(runtime.call(app.endpoints[0], {"key": "ordered"}))
    assert result == Report(key="prepared-ordered", check="prices")
    assert [e[0] for e in events] == [
        "prepare",
        "model-resolution",
        "inspect",
        "inspect",
        "verify",
        "finalize",
    ]
    assert len(turns) == 3


def declare_variant(kind):
    def prepare(key: str = "fixed", mode: Literal["a", "b"] = "a") -> Prepared:
        return Prepared(key=key)

    def inspect(key: str, check: Literal["stock", "prices"]) -> Snapshot:
        return Snapshot(key=key, check=check)

    def verify(key: str, check: str) -> Verified:
        return Verified(key=key, check=check)

    def finish(key: str, check: str) -> Report:
        return Report(key=key, check=check)

    binding: dict[str, Any] = (
        {} if kind == "no-global-request" else {"key": FromRequest("key")}
    )
    if kind == "prefix-choice":
        binding["mode"] = AgentChoice()
    first = Operation(prepare, bind=binding, output=Prepared)
    middle = Operation(
        inspect,
        bind={
            "key": FromResult(
                first, "key", invocation="final" if kind == "qualified-single" else None
            ),
            "check": AgentChoice(),
        },
        output=Snapshot,
    )
    checked = Operation(
        verify,
        bind={
            "key": FromResult(
                middle,
                "key",
                invocation=None if kind == "unqualified-repeat" else "final",
            ),
            "check": FromResult(middle, "check", invocation="final"),
        },
        output=Verified,
    )
    last = Operation(
        finish,
        bind={"key": FromResult(checked, "key"), "check": FromResult(checked, "check")},
        output=Report,
    )
    app = Summon("stage-chain-admission")
    if kind == "repeated-terminal":
        final_repeat = Operation(
            inspect,
            bind={"key": FromResult(first, "key"), "check": AgentChoice()},
            output=Snapshot,
        )

        @app("/review")
        def repeated_terminal(
            request: Request,
            prefix=Required(first, calls=Exactly(1)),
            final=Required(final_repeat, calls=Between(1, 3)),
        ) -> Snapshot:
            """Prepare and inspect within bounds."""
            ...
    elif kind == "two-stages":
        another = Operation(
            inspect,
            bind={
                "key": FromResult(middle, "key", invocation="final"),
                "check": AgentChoice(),
            },
            output=Snapshot,
        )

        @app("/review")
        def two_stages(
            request: Request,
            prefix=Required(first, calls=Exactly(1)),
            one=Required(middle, calls=Between(1, 3)),
            two=Required(another, calls=Between(1, 3)),
            v=Required(checked, calls=Exactly(1)),
            result=Required(last, calls=Exactly(1)),
        ) -> Report:
            """Prepare, inspect within bounds and return a report."""
            ...
    elif kind == "disconnected":
        extra = Operation(prepare, bind={"key": FromRequest("key")}, output=Prepared)

        @app("/review")
        def disconnected(
            request: Request,
            prefix=Required(first, calls=Exactly(1)),
            work=Required(middle, calls=Between(1, 3)),
            v=Required(checked, calls=Exactly(1)),
            result=Required(last, calls=Exactly(1)),
            unrelated=Required(extra, calls=Exactly(1)),
        ) -> Report:
            """Prepare, inspect within bounds and return a report."""
            ...
    else:

        @app("/review")
        def endpoint(
            request: Request,
            prefix=Required(first, calls=Exactly(1)),
            work=Required(middle, calls=Between(1, 3)),
            v=Required(checked, calls=Exactly(1)),
            result=Required(last, calls=Exactly(1)),
        ) -> Report:
            """Prepare, inspect within bounds, verify and finalize."""
            ...

    return app


@pytest.mark.parametrize(
    "kind",
    [
        "no-global-request",
        "prefix-choice",
        "qualified-single",
        "unqualified-repeat",
        "repeated-terminal",
        "two-stages",
        "disconnected",
    ],
)
def test_unsupported_combinations_reject_before_serving(kind):
    with pytest.raises(TypeError):
        declare_variant(kind)


def test_resolved_chains_with_no_stage_retain_the_existing_executor():
    def prepare(key: str) -> Prepared:
        return Prepared(key=key)

    def finish(key: str) -> Report:
        return Report(key=key, check="resolved")

    first = Operation(prepare, bind={"key": FromRequest("key")}, output=Prepared)
    last = Operation(finish, bind={"key": FromResult(first, "key")}, output=Report)
    app = Summon("resolved-control", model="invalid:no-model")

    @app("/resolved")
    def endpoint(
        request: Request,
        p=Required(first, calls=Exactly(1)),
        r=Required(last, calls=Exactly(1)),
    ) -> Report:
        """Prepare and finalize without any unresolved choices."""
        ...

    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "direct"}))
    assert result == Report(key="direct", check="resolved")
