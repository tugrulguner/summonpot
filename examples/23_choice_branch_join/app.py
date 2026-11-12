"""Level 23: independent quote work with one bounded shipping choice.

Current-source/unreleased lesson; published v0.15.0 rejects this graph shape.
Tariffs are application-defined calculations, not live carrier quotes.
"""

from typing import Literal

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


class QuoteRequest(BaseModel):
    quantity: int = Field(ge=1, le=100)
    unit_price_cents: int = Field(ge=0)
    unit_weight_grams: int = Field(ge=1, le=100_000)
    max_delivery_days: int = Field(default=4, ge=1, le=4)


class Merchandise(BaseModel):
    cents: int


class ShippingOffer(BaseModel):
    service: Literal["standard", "express"]
    cents: int
    delivery_days: int


class ChosenShipping(BaseModel):
    service: str
    cents: int


class QuoteResponse(BaseModel):
    merchandise_cents: int
    shipping_cents: int
    service: str
    total_cents: int


# Function and its exact Operation are kept together.
def price_merchandise(quantity: int, unit_price_cents: int) -> Merchandise:
    return Merchandise(cents=quantity * unit_price_cents)


merchandise = Operation(
    price_merchandise,
    bind={
        "quantity": FromRequest("quantity"),
        "unit_price_cents": FromRequest("unit_price_cents"),
    },
)


def list_shipping(
    quantity: int, unit_weight_grams: int, max_delivery_days: int
) -> list[ShippingOffer]:
    blocks = (quantity * unit_weight_grams + 499) // 500
    offers = [
        ShippingOffer(service="standard", cents=400 + 100 * blocks, delivery_days=4),
        ShippingOffer(service="express", cents=900 + 150 * blocks, delivery_days=1),
    ]
    return [offer for offer in offers if offer.delivery_days <= max_delivery_days]


offers = Operation(
    list_shipping,
    bind={
        "quantity": FromRequest("quantity"),
        "unit_weight_grams": FromRequest("unit_weight_grams"),
        "max_delivery_days": FromRequest("max_delivery_days"),
    },
)


def apply_shipping(offer: ShippingOffer) -> ChosenShipping:
    return ChosenShipping(service=offer.service, cents=offer.cents)


shipping = Operation(
    apply_shipping,
    bind={
        "offer": AgentChoice(from_result=offers),
    },
)


def combine_quote(
    merchandise_cents: int, shipping_cents: int, service: str
) -> QuoteResponse:
    return QuoteResponse(
        merchandise_cents=merchandise_cents,
        shipping_cents=shipping_cents,
        service=service,
        total_cents=merchandise_cents + shipping_cents,
    )


quote = Operation(
    combine_quote,
    bind={
        "merchandise_cents": FromResult(merchandise, "cents"),
        "shipping_cents": FromResult(shipping, "cents"),
        "service": FromResult(shipping, "service"),
    },
)

summon = Summon("shipping-quote")


@summon("/quotes/shipping-choice")
def create_quote(
    request: QuoteRequest,
    result=Required(quote, calls=Exactly(1)),
    subtotal=Required(merchandise, calls=Exactly(1)),
    candidates=Required(offers, calls=Exactly(1)),
    selection=Required(shipping, calls=Exactly(1)),
) -> QuoteResponse:
    """Choose the lowest-price offered shipping service and return its exact combined quote."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
