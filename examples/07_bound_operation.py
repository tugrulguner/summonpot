"""Level 7: one exactly-once operation with mixed argument authority."""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    Operation,
    Required,
    Summon,
)


class CustomerRequest(BaseModel):
    customer_id: str


class CustomerRecord(BaseModel):
    customer_id: str
    name: str
    status: Literal["active", "paused"]
    format: Literal["summary", "detailed"]


class CustomerView(BaseModel):
    customer_id: str
    display: str = Field(
        min_length=1,
        description="Render the returned customer's name and status, not the format label.",
    )


class _Customer(TypedDict):
    name: str
    status: Literal["active", "paused"]


_CUSTOMERS: dict[str, _Customer] = {
    "customer-7": {"name": "Ada", "status": "active"},
    "customer-9": {"name": "Grace", "status": "paused"},
}


def load_customer(
    customer_id: str,
    format: Literal["summary", "detailed"],
) -> CustomerRecord:
    """Load one approved customer record in the selected display format."""
    record = _CUSTOMERS[customer_id]
    return CustomerRecord(
        customer_id=customer_id,
        name=record["name"],
        status=record["status"],
        format=format,
    )


customer_lookup = Operation(
    load_customer,
    bind={
        "customer_id": FromRequest("customer_id"),
        "format": AgentChoice(),
    },
    output=CustomerRecord,
)

summon = Summon("bound-customer-service")


@summon("/customers/view")
def customer_view(
    request: CustomerRequest,
    customer=Required(customer_lookup, calls=Exactly(1)),
) -> CustomerView:
    """Load the requested customer once, then compose the view from the returned record.

    Copy customer_id from that record. Render its actual name and status in display:
    for summary use "{name} — {status}"; for detailed include those same facts in a
    fuller description. The format value is a rendering choice, never display content.
    """
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
