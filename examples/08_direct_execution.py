"""Level 8: one fully resolved operation executes without a model."""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from summonpot import Exactly, FromRequest, Operation, Required, Summon


class QuoteRequest(BaseModel):
    unit_price_cents: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)
    tax_rate_percent: Decimal = Field(ge=0, le=30)


class QuoteResponse(BaseModel):
    subtotal_cents: int
    tax_cents: int
    total_cents: int


def calculate_quote(
    unit_price_cents: int,
    quantity: int,
    tax_rate_percent: Decimal,
) -> QuoteResponse:
    """Calculate an exact quote using the application's approved pricing rules."""
    subtotal = unit_price_cents * quantity
    tax = (Decimal(subtotal) * tax_rate_percent / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return QuoteResponse(
        subtotal_cents=subtotal,
        tax_cents=int(tax),
        total_cents=subtotal + int(tax),
    )


quote_operation = Operation(
    calculate_quote,
    bind={
        "unit_price_cents": FromRequest("unit_price_cents"),
        "quantity": FromRequest("quantity"),
        "tax_rate_percent": FromRequest("tax_rate_percent"),
    },
    output=QuoteResponse,
)

summon = Summon("direct-quote-service")


@summon("/quotes/direct")
def create_quote(
    request: QuoteRequest,
    quote=Required(quote_operation, calls=Exactly(1)),
) -> QuoteResponse:
    """Return the exact approved quote through its one complete operation path."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
