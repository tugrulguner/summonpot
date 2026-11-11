"""Level 20: independent quote calculations join without model orchestration.

Included from version 0.15.0; this branch-and-join shape is not in published v0.14.0.
"""

from pydantic import BaseModel, Field

from summonpot import Exactly, FromRequest, FromResult, Operation, Required, Summon


class QuoteRequest(BaseModel):
    unit_price_cents: int = Field(ge=0)
    quantity: int = Field(ge=1, le=100)
    unit_weight_grams: int = Field(ge=1, le=100_000)


class Merchandise(BaseModel):
    subtotal_cents: int


class Shipping(BaseModel):
    shipping_cents: int


class QuoteResponse(BaseModel):
    subtotal_cents: int
    shipping_cents: int
    total_cents: int


def calculate_merchandise(unit_price_cents: int, quantity: int) -> Merchandise:
    """Calculate the exact merchandise subtotal from the validated request."""
    return Merchandise(subtotal_cents=unit_price_cents * quantity)


merchandise = Operation(
    calculate_merchandise,
    bind={
        "unit_price_cents": FromRequest("unit_price_cents"),
        "quantity": FromRequest("quantity"),
    },
)


def calculate_shipping(unit_weight_grams: int, quantity: int) -> Shipping:
    """Apply the application's tariff: 499 cents plus 199 per extra 500 g block."""
    weight = unit_weight_grams * quantity
    additional_blocks = max(0, (weight - 500 + 499) // 500)
    return Shipping(shipping_cents=499 + 199 * additional_blocks)


shipping = Operation(
    calculate_shipping,
    bind={
        "unit_weight_grams": FromRequest("unit_weight_grams"),
        "quantity": FromRequest("quantity"),
    },
)


def combine_quote(subtotal_cents: int, shipping_cents: int) -> QuoteResponse:
    """Return the combined canonical calculation; do not charge or reserve anything."""
    return QuoteResponse(
        subtotal_cents=subtotal_cents,
        shipping_cents=shipping_cents,
        total_cents=subtotal_cents + shipping_cents,
    )


quote = Operation(
    combine_quote,
    bind={
        "subtotal_cents": FromResult(merchandise, "subtotal_cents"),
        "shipping_cents": FromResult(shipping, "shipping_cents"),
    },
)

summon = Summon("branch-join-quote")


@summon("/quotes/combined")
def create_quote(
    request: QuoteRequest,
    result=Required(quote, calls=Exactly(1)),
    merchandise_result=Required(merchandise, calls=Exactly(1)),
    shipping_result=Required(shipping, calls=Exactly(1)),
) -> QuoteResponse:
    """Calculate merchandise and shipping, then return their exact combined quote."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
