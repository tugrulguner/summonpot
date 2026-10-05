"""Level 9: hardened explicit contracts keep authority at the boundary."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from summonpot import Exactly, FromRequest, Operation, Required, Summon

OPERATION_CALLS: list[tuple[str, str]] = []


class CustomerRequest(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    customer_id: str = Field(alias="customerId", min_length=1)
    region: str = "us"


class CustomerView(BaseModel):
    customer_id: str = Field(serialization_alias="customerId")
    region: str


def load_customer(
    customer_id: Annotated[str, Field(min_length=3)],
    region: str,
) -> CustomerView:
    """Load the approved customer projection from application-owned code."""
    OPERATION_CALLS.append((customer_id, region))
    return CustomerView(customer_id=customer_id, region=region)


customer_operation = Operation(
    load_customer,
    bind={
        "customer_id": FromRequest("customer_id"),
        "region": FromRequest("region"),
    },
    output=CustomerView,
)

summon = Summon("contract-boundary-service")


@summon("/customers/view")
def customer_view(
    request: CustomerRequest,
    customer=Required(customer_operation, calls=Exactly(1)),
) -> CustomerView:
    """Return the approved customer projection through one exact operation."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
