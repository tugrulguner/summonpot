"""Registration controls for the generic marked checkpoint region."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, Field, StrictBool
from pydantic_ai.models.function import FunctionModel

from summonpot import (
    AtMost,
    Between,
    Depends,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime


class Request(BaseModel):
    key: str


class Check(BaseModel):
    key: str
    accepted: StrictBool


class AliasedCheck(BaseModel):
    key: str
    accepted: StrictBool = Field(serialization_alias="exported")


class CoerciveCheck(BaseModel):
    key: str
    accepted: bool


class Receipt(BaseModel):
    key: str


class Report(BaseModel):
    key: str
    accepted: bool


class StringSubclass(str):
    pass


def declared(
    *,
    marker: Any = "accepted",
    maximum=3,
    negative_maximum=2,
    output: type[BaseModel] = Check,
    final=True,
    detached=False,
):
    def check(key: str):
        return output(key=key, accepted=True)

    check.__annotations__ = {"key": str, "return": output}

    def advance(key: str) -> Receipt:
        raise AssertionError("valid input never requires negative work")

    def finish(key: str, accepted: bool) -> Report:
        return Report(key=key, accepted=accepted)

    a = Operation(check, bind={"key": FromRequest("key")}, output=output)
    b = Operation(advance, bind={"key": FromResult(a, "key")}, output=Receipt)
    terminal_producer = a.with_bind(key=FromRequest("key")) if detached else a
    c = Operation(
        finish,
        bind={
            field: FromResult(
                terminal_producer, field, invocation="final" if final else None
            )
            for field in ("key", "accepted")
        },
        output=Report,
    )

    def forbidden(messages, info):
        raise AssertionError("no inference in registration controls")

    runtime = Runtime(model=FunctionModel(forbidden))
    app = Summon("admission-controls", runtime=runtime)

    @app("/check")
    def endpoint(
        request: Request,
        terminal=Required(c, calls=Exactly(1)),
        optional=Depends(b, calls=AtMost(negative_maximum)),
        status=Required(a, calls=Between(1, maximum), until=marker),
    ) -> Report:
        """Advance state only while the strict check has not accepted it."""
        ...

    return app


def test_canonical_field_marker_accepts_serialization_alias_without_using_alias():
    app = declared(output=AliasedCheck)
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"key": "A"}))
    assert result == Report(key="A", accepted=True)
    with pytest.raises((TypeError, ValueError)):
        declared(output=AliasedCheck, marker="exported")


@pytest.mark.parametrize(
    "marker",
    ["", True, 0, ["accepted"], StringSubclass("accepted"), "missing", "accepted.path"],
)
def test_marker_values_reject_after_positive_control(marker):
    declared()
    with pytest.raises((TypeError, ValueError)):
        declared(marker=marker)


@pytest.mark.parametrize(
    "options",
    [
        {"maximum": 2},
        {"negative_maximum": 1},
        {"maximum": 1, "negative_maximum": 0},
        {"output": CoerciveCheck},
        {"final": False},
        {"detached": True},
    ],
)
def test_invalid_region_rejects_after_positive_control(options):
    declared()
    with pytest.raises((TypeError, ValueError)):
        declared(**options)
