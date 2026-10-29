"""SQLite order flow: choose a product, then a compatible delivery option."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon

DB_PATH = Path(os.environ.get("MULTIPLE_CHOICE_DB", "multiple-choice.sqlite3"))


class OrderRequest(BaseModel):
    category: str = Field(min_length=1)
    quantity: int = Field(ge=1, le=20)
    idempotency_key: str = Field(min_length=1, max_length=100)


class Product(BaseModel):
    product_id: str
    name: str
    category: str
    stock: int


class Delivery(BaseModel):
    delivery_id: str
    product_id: str
    name: str
    price_cents: int


class Receipt(BaseModel):
    order_id: str
    idempotency_key: str
    product_id: str
    delivery_id: str
    quantity: int
    total_cents: int
    remaining_stock: int


def connect() -> sqlite3.Connection:
    """Open an application-owned short-lived SQLite connection."""
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    """Create the small catalog and durable order/receipt tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                category TEXT NOT NULL, stock INTEGER NOT NULL CHECK(stock >= 0),
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id TEXT PRIMARY KEY, product_id TEXT NOT NULL
                    REFERENCES products(product_id), name TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0), active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                product_id TEXT NOT NULL, delivery_id TEXT NOT NULL, quantity INTEGER NOT NULL,
                total_cents INTEGER NOT NULL, remaining_stock INTEGER NOT NULL
            );
            """
        )
        db.executemany(
            "INSERT OR IGNORE INTO products(product_id,name,category,stock) VALUES(?,?,?,?)",
            [
                ("tea", "Tea", "grocery", 8),
                ("tea-green", "Green Tea", "grocery", 6),
                ("coffee", "Coffee", "coffee", 5),
                ("notebook", "Notebook", "stationery", 0),
            ],
        )
        db.executemany(
            "INSERT OR IGNORE INTO deliveries(delivery_id,product_id,name,price_cents) VALUES(?,?,?,?)",
            [
                ("tea-green-ground", "tea-green", "Ground courier", 300),
                ("tea-ground", "tea", "Ground courier", 300),
                ("tea-express", "tea", "Express courier", 700),
                ("coffee-ground", "coffee", "Ground courier", 350),
            ],
        )


def find_products(category: str) -> list[Product]:
    """Read the requested category from SQLite; no model-created catalog data."""
    initialize_database()
    with connect() as db:
        rows = db.execute(
            "SELECT product_id,name,category,stock FROM products WHERE category=? AND active=1 AND stock>0 ORDER BY product_id",
            (category,),
        ).fetchall()
    return [Product(**dict(row)) for row in rows]


def compatible_deliveries(product: Product) -> list[Delivery]:
    """Read delivery candidates for the canonical selected product identifier."""
    with connect() as db:
        rows = db.execute(
            "SELECT delivery_id,product_id,name,price_cents FROM deliveries WHERE product_id=? AND active=1 ORDER BY delivery_id",
            (product.product_id,),
        ).fetchall()
    return [Delivery(**dict(row)) for row in rows]


def persist_order(
    product: Product, delivery: Delivery, quantity: int, idempotency_key: str
) -> Receipt:
    """Validate compatibility and atomically persist receipt plus stock change."""
    initialize_database()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if prior is not None:
            if (prior["product_id"], prior["delivery_id"], prior["quantity"]) != (
                product.product_id,
                delivery.delivery_id,
                quantity,
            ):
                raise ValueError("idempotency key was used for a different order")
            row = prior
        else:
            selected = db.execute(
                "SELECT product_id,stock FROM products WHERE product_id=? AND active=1",
                (product.product_id,),
            ).fetchone()
            option = db.execute(
                "SELECT product_id,price_cents FROM deliveries WHERE delivery_id=? AND active=1",
                (delivery.delivery_id,),
            ).fetchone()
            if (
                selected is None
                or option is None
                or option["product_id"] != selected["product_id"]
            ):
                raise ValueError("delivery option does not belong to selected product")
            if selected["stock"] < quantity:
                raise ValueError("insufficient stock")
            remaining = selected["stock"] - quantity
            db.execute(
                "UPDATE products SET stock=? WHERE product_id=?",
                (remaining, product.product_id),
            )
            order_id = f"order-{idempotency_key}"
            total = option["price_cents"] * quantity
            db.execute(
                "INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
                (
                    order_id,
                    idempotency_key,
                    product.product_id,
                    delivery.delivery_id,
                    quantity,
                    total,
                    remaining,
                ),
            )
            row = db.execute(
                "SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
    return Receipt(
        order_id=row["order_id"],
        idempotency_key=row["idempotency_key"],
        product_id=row["product_id"],
        delivery_id=row["delivery_id"],
        quantity=row["quantity"],
        total_cents=row["total_cents"],
        remaining_stock=row["remaining_stock"],
    )


initialize_database()
products = Operation(
    find_products, bind={"category": FromRequest("category")}, output=list[Product]
)
deliveries = Operation(
    compatible_deliveries,
    bind={"product": AgentChoice(from_result=products)},
    output=list[Delivery],
)
commit = Operation(
    persist_order,
    bind={
        "product": AgentChoice(from_result=products),
        "delivery": AgentChoice(from_result=deliveries),
        "quantity": FromRequest("quantity"),
        "idempotency_key": FromRequest("idempotency_key"),
    },
    output=Receipt,
)

summon = Summon("sqlite-multiple-choice-orders")


@summon("/orders")
def place_order(
    request: OrderRequest,
    found=Required(products, calls=Exactly(1)),
    options=Required(deliveries, calls=Exactly(1)),
    receipt=Required(commit, calls=Exactly(1)),
) -> Receipt:
    """Select a matching product and one of its delivery options, then order it."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
