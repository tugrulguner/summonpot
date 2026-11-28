"""Current-source / unreleased: independent shipping and packaging choices.

Application-defined tariff calculations, not carrier services or charges.
Published v0.15.0 does not support this branch/join declaration."""

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


class Request(BaseModel):
    units: int = Field(ge=1, le=100)
    goods_cents: int = Field(ge=0)
    rush: bool = False
    protective: bool = False


class Option(BaseModel):
    name: str
    cents: int


class Line(BaseModel):
    name: str
    cents: int


class Quote(BaseModel):
    shipping: str
    packaging: str
    total_cents: int


def shipping_options(units: int, rush: bool) -> list[Option]:
    options = [
        Option(name="standard", cents=250 + 50 * units),
        Option(name="express", cents=600 + 80 * units),
    ]
    return [x for x in options if not rush or x.name == "express"]


shipping_offers = Operation(
    shipping_options, bind={"units": FromRequest("units"), "rush": FromRequest("rush")}
)


def choose_shipping(option: Option) -> Line:
    return Line(name=option.name, cents=option.cents)


shipping = Operation(
    choose_shipping, bind={"option": AgentChoice(from_result=shipping_offers)}
)


def packaging_options(units: int, protective: bool) -> list[Option]:
    options = [
        Option(name="lightweight", cents=100 + 15 * units),
        Option(name="protective", cents=250 + 25 * units),
    ]
    return [x for x in options if not protective or x.name == "protective"]


packaging_offers = Operation(
    packaging_options,
    bind={"units": FromRequest("units"), "protective": FromRequest("protective")},
)


def choose_packaging(option: Option) -> Line:
    return Line(name=option.name, cents=option.cents)


packaging = Operation(
    choose_packaging, bind={"option": AgentChoice(from_result=packaging_offers)}
)


def finish(
    goods_cents: int,
    shipping_cents: int,
    packaging_cents: int,
    shipping_name: str,
    packaging_name: str,
) -> Quote:
    return Quote(
        shipping=shipping_name,
        packaging=packaging_name,
        total_cents=goods_cents + shipping_cents + packaging_cents,
    )


quote = Operation(
    finish,
    bind={
        "goods_cents": FromRequest("goods_cents"),
        "shipping_cents": FromResult(shipping, "cents"),
        "packaging_cents": FromResult(packaging, "cents"),
        "shipping_name": FromResult(shipping, "name"),
        "packaging_name": FromResult(packaging, "name"),
    },
)

summon = Summon("two-independent-choices")


@summon("/quotes/fulfillment")
def quote_endpoint(
    request: Request,
    a=Required(shipping_offers, calls=Exactly(1)),
    b=Required(shipping, calls=Exactly(1)),
    c=Required(packaging_offers, calls=Exactly(1)),
    d=Required(packaging, calls=Exactly(1)),
    e=Required(quote, calls=Exactly(1)),
) -> Quote:
    """Choose the lowest-price offered shipping and packaging and return the exact quote."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
