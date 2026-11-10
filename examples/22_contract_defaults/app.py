"""Current source / unreleased lesson 22: callable defaults and full annotations.

Output inference requires current source. For published-version compatibility,
declare output=QuoteOutput explicitly on the Operation.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from summonpot import Exactly, FromRequest, Operation, Required, Summon


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_price_cents: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)


class QuoteResponse(BaseModel):
    subtotal_cents: int = Field(ge=0)
    discount_cents: int = Field(ge=0)
    total_cents: int = Field(ge=0)


QuoteOutput = Annotated[
    QuoteResponse, Field(description="Quote after the application discount.")
]


async def calculate_quote(
    unit_price_cents: Annotated[int, Field(gt=0)],
    quantity: Annotated[int, Field(ge=1, le=10)],
    discount_percent: Annotated[int, Field(ge=0, le=100)] = 5,
) -> QuoteOutput:
    """Apply the application discount, rounding discount cents down."""
    subtotal = unit_price_cents * quantity
    discount = subtotal * discount_percent // 100
    return QuoteResponse(
        subtotal_cents=subtotal,
        discount_cents=discount,
        total_cents=subtotal - discount,
    )


quote_operation = Operation(
    calculate_quote,
    bind={
        "unit_price_cents": FromRequest("unit_price_cents"),
        "quantity": FromRequest("quantity"),
    },
)
# discount_percent is deliberately absent from bind: the callable owns its default.
summon = Summon("contract-default-quotes")


@summon("/quotes/defaults")
def quote(
    request: QuoteRequest,
    result=Required(quote_operation, calls=Exactly(1)),
) -> QuoteOutput:
    """Return the exact quote calculated with the application's default discount."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
