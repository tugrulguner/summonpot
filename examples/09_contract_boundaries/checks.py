"""Run the v0.9 contract-boundary checks without provider credentials."""

import asyncio
import json

from app import (
    OPERATION_CALLS,
    CustomerRequest,
    CustomerView,
    customer_operation,
    summon,
)
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from summonpot import AtLeast, Required, Summon
from summonpot.runtime import Runtime
from summonpot.server import build_app


def _fail_closed_registration_check() -> bool:
    invalid = Summon("unsupported-explicit-contract")
    try:

        @invalid("/customers")
        def customers(
            request: CustomerRequest,
            customer=Required(customer_operation, calls=AtLeast(2)),
        ) -> CustomerView:
            """This unsupported explicit call bound must fail before serving."""
            ...
    except TypeError as error:
        return "cannot enforce the declared call bound" in str(error)
    return False


def _output_namespace_check() -> bool:
    class AmbiguousOutput(BaseModel):
        first: str = Field(serialization_alias="customerId")
        customer_id: str = Field(serialization_alias="customerId")

    invalid = Summon("ambiguous-output-contract")
    try:

        @invalid("/ambiguous")
        def ambiguous() -> AmbiguousOutput:
            """This duplicate emitted key must fail before serving."""
            ...
    except TypeError as error:
        return "duplicate" in str(error).lower()
    return False


async def run_checks() -> dict[str, bool]:
    """Exercise the four user-visible v0.9 boundary guarantees."""
    OPERATION_CALLS.clear()
    runtime = Runtime(model="invalid-provider:no-model")
    endpoint = summon.endpoints[0]

    raw = await runtime.call(endpoint, {"customerId": "customer-7"})
    response = TestClient(build_app(summon)).post(
        "/customers/view", json={"customerId": "customer-7"}
    )
    expected = {"customerId": "customer-7", "region": "us"}
    raw_http_parity = raw.model_dump(by_alias=True) == response.json() == expected

    starts_before_rejection = len(OPERATION_CALLS)
    try:
        await runtime.call(endpoint, {"customerId": "x"})
    except RuntimeError as error:
        receiving_constraint = (
            "receiving parameter contract" in str(error)
            and len(OPERATION_CALLS) == starts_before_rejection
        )
    else:
        receiving_constraint = False

    return {
        "fail_closed_registration": _fail_closed_registration_check(),
        "receiving_constraint": receiving_constraint,
        "output_namespace": _output_namespace_check(),
        "raw_http_parity": raw_http_parity,
    }


if __name__ == "__main__":
    result = asyncio.run(run_checks())
    if not all(result.values()):
        raise SystemExit(json.dumps(result, sort_keys=True))
    print(json.dumps(result, sort_keys=True))
