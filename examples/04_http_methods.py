"""Level 4: GET and POST endpoints sharing one resource path."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from summonpot import Required, Summon

PRODUCTS = {
    "notebook": {"category": "stationery", "price_cents": 1299},
    "pen": {"category": "stationery", "price_cents": 299},
    "headphones": {"category": "electronics", "price_cents": 7999},
}


class ProductView(BaseModel):
    sku: str
    category: str
    price_cents: int


class ProductList(BaseModel):
    products: list[ProductView]


class ReservationRequest(BaseModel):
    customer_id: str
    sku: str


class ReservationResponse(BaseModel):
    reservation_id: str
    status: Literal["reserved"]


def search_products(
    category: str | None = None,
    max_price_cents: int | None = None,
) -> list[dict[str, object]]:
    """Return catalog products matching the exact optional filters."""
    matches: list[dict[str, object]] = []
    for sku, product in PRODUCTS.items():
        if category is not None and product["category"] != category:
            continue
        if max_price_cents is not None and product["price_cents"] > max_price_cents:
            continue
        matches.append({"sku": sku, **product})
    return matches


def reserve_product(customer_id: str, sku: str) -> dict[str, str]:
    """Return a demo receipt for a known catalog product; no stock is held."""
    if sku not in PRODUCTS:
        raise ValueError(f"Unknown product: {sku}")
    return {
        "reservation_id": f"reservation-{customer_id}-{sku}",
        "status": "reserved",
    }


summon = Summon("catalog")


@summon("/products", method="GET")
def list_products(
    category: str | None = None,
    max_price_cents: Annotated[int | None, Field(gt=0)] = None,
    search=Required(search_products),
) -> ProductList:
    """Call search_products with the supplied query filters and return every exact match under the products field."""
    ...


@summon("/products", method="POST")
def reserve(
    request: ReservationRequest,
    reservation=Required(reserve_product),
) -> ReservationResponse:
    """Reserve the requested product and return the exact reservation receipt."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
