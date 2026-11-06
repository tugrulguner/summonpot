"""Output annotation completion is registration-only and preserves explicit authority."""

import asyncio
from typing import Annotated, Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime


class OutputRequest(BaseModel):
    value: int


class OutputResponse(BaseModel):
    value: int


def test_omitted_operation_output_executes_model_free_without_mutating_declaration():
    starts = []

    def calculate(value: int) -> OutputResponse:
        starts.append(value)
        return OutputResponse(value=value)

    op = Operation(calculate, bind={"value": FromRequest("value")})
    app = Summon("output-inference", runtime=Runtime(model="invalid:no-provider"))

    @app("/run")
    def endpoint(
        request: OutputRequest, result=Required(op, calls=Exactly(1))
    ) -> OutputResponse:
        """Return the exact validated calculation."""
        ...

    assert op.output is None
    result = asyncio.run(app._runtime.call(app.endpoints[0], {"value": 7}))
    assert result.value == 7 and starts == [7]


class Intermediate(BaseModel):
    value: int


@pytest.mark.parametrize("producer_choice", [False, True])
def test_inferred_producer_references_preserve_canonical_identity(producer_choice):
    def produce(value: int):
        return (
            [Intermediate(value=value)]
            if producer_choice
            else Intermediate(value=value)
        )

    produce.__annotations__["return"] = (
        list[Intermediate] if producer_choice else Intermediate
    )

    def finish(item: Intermediate) -> OutputResponse:
        return OutputResponse(value=item.value)

    def finish_field(value: int) -> OutputResponse:
        return OutputResponse(value=value)

    a = Operation(produce, bind={"value": FromRequest("value")})
    b = (
        Operation(finish, bind={"item": AgentChoice(from_result=a)})
        if producer_choice
        else Operation(finish_field, bind={"value": FromResult(a, "value")}, after=(a,))
    )
    app = Summon("chain", runtime=Runtime(model="invalid:no-provider"))

    @app("/run")
    def endpoint(
        request: OutputRequest,
        first=Required(a, calls=Exactly(1)),
        last=Required(b, calls=Exactly(1)),
    ) -> OutputResponse:
        """Return the canonical result of the inferred chain."""
        ...

    with TestClient(
        __import__("summonpot.server", fromlist=["build_app"]).build_app(app)
    ) as client:
        response = client.post("/run", json={"value": 8})
    assert response.status_code == 200 and response.json() == {"value": 8}
    assert a.output is None and b.output is None
    assert b.bind is not None
    if producer_choice:
        assert b.bind["item"].from_result is a
    else:
        assert b.bind["value"].operation is a and b.after == (a,)


@pytest.mark.parametrize("annotation", [None, Any, "MissingOutputType"])
def test_unusable_return_requires_explicit_output(annotation):
    def calculate(value: int):
        return OutputResponse(value=value)

    if annotation is not None:
        calculate.__annotations__["return"] = annotation
    app = Summon("invalid")
    with pytest.raises((TypeError, ValueError)):

        @app("/run")
        def endpoint(
            request: OutputRequest,
            result=Required(
                Operation(calculate, bind={"value": FromRequest("value")}),
                calls=Exactly(1),
            ),
        ) -> OutputResponse:
            """Reject an unavailable output contract."""
            ...


def test_explicit_output_remains_authoritative_without_return_annotation():
    def calculate(value: int):
        return OutputResponse(value=value)

    op = Operation(
        calculate, bind={"value": FromRequest("value")}, output=OutputResponse
    )
    app = Summon("explicit", runtime=Runtime(model="invalid:no-provider"))

    @app("/run")
    def endpoint(
        request: OutputRequest, result=Required(op, calls=Exactly(1))
    ) -> OutputResponse:
        """Retain the explicit application output contract."""
        ...

    assert asyncio.run(app._runtime.call(app.endpoints[0], {"value": 3})).value == 3
    assert app.endpoints[0].tools[0].contract is op


def test_annotated_output_and_registration_snapshot():
    annotation = Annotated[OutputResponse, Field(description="inferred metadata")]

    def calculate(value: int):
        return OutputResponse(value=value)

    calculate.__annotations__["return"] = annotation
    op = Operation(calculate, bind={"value": FromRequest("value")})
    app = Summon("annotated", runtime=Runtime(model="invalid:no-provider"))

    def endpoint(request: OutputRequest, result=Required(op, calls=Exactly(1))):
        """Preserve the full declared response annotation."""
        ...

    endpoint.__annotations__["return"] = annotation
    app("/run")(endpoint)
    contract = app.endpoints[0].tools[0].contract
    assert contract is not None and contract.output is annotation
    calculate.__annotations__["return"] = str
    assert asyncio.run(app._runtime.call(app.endpoints[0], {"value": 4})).value == 4
    assert op.output is None


def test_inferred_checkpoint_outputs_keep_closed_result_authority(monkeypatch):
    import test_checkpoint

    originals = []

    def inferred_operation(*args, **kwargs):
        kwargs.pop("output", None)
        op = Operation(*args, **kwargs)
        originals.append(op)
        return op

    monkeypatch.setattr(test_checkpoint, "Operation", inferred_operation)
    test_checkpoint.test_already_valid_checkpoint_skips_optional_work_and_model()
    assert len(originals) == 3 and all(op.output is None for op in originals)


@pytest.mark.parametrize("kind", ["bound", "callable", "partial"])
def test_supported_callable_annotations_are_inferred(kind):
    from functools import partial

    class Service:
        def calculate(self, value: int) -> OutputResponse:
            return OutputResponse(value=value)

        def __call__(self, value: int) -> OutputResponse:
            return OutputResponse(value=value)

    def calculate(value: int, offset: int = 0) -> OutputResponse:
        return OutputResponse(value=value + offset)

    fn = (
        Service().calculate
        if kind == "bound"
        else Service()
        if kind == "callable"
        else partial(calculate, offset=0)
    )
    op = Operation(fn, bind={"value": FromRequest("value")})
    app = Summon("callable", runtime=Runtime(model="invalid:no-provider"))

    @app("/run")
    def endpoint(
        request: OutputRequest, result=Required(op, calls=Exactly(1))
    ) -> OutputResponse:
        """Infer output from the supported callable annotation owner."""
        ...

    assert asyncio.run(app._runtime.call(app.endpoints[0], {"value": 5})).value == 5


def test_omitted_input_binding_is_not_inferred():
    def calculate(value: int) -> OutputResponse:
        return OutputResponse(value=value)

    app = Summon("explicit-inputs")
    with pytest.raises(TypeError):

        @app("/run")
        def endpoint(
            request: OutputRequest,
            result=Required(Operation(calculate), calls=Exactly(1)),
        ) -> OutputResponse:
            """Do not infer trusted input sources."""
            ...
