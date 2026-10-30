# SQLite product and delivery choices

This example serves one fixed `POST /orders` goal: query an active in-stock product,
choose a product, query its application-owned compatible delivery options, choose a
delivery, then atomically write an order, decrement stock, and return the persisted
receipt. The request contains business fields only; it has no action or runtime selector.
All SQL values are parameterized, and the write rechecks delivery/product membership
inside the SQLite write transaction.

## Execution boundary

Framework-owned progression across multiple producer-backed choices is current unreleased source behavior; published v0.14.0 optimizes exactly one producer-backed choice. The eligible chain still needs a Pydantic request with at least one `FromRequest`, two or more uniquely ordered required `Exactly(1)` operations, supported request/result/authenticated-context inputs or immutable defaults, and an exact full terminal response annotation. At every ready consumer, Summonpot checks all producer-backed domains before selection or start. Singleton choices bind locally; when a frontier is ambiguous, one private selector receives only safe projected request data and bounded inert evidence plus opaque tokens—no business tools, principal or ledger. After local token and receiving validation, the shared invocation kernel starts the exact operation and progression continues. The unique terminal operation supplies the canonical response without a final model acknowledgment. Request-wide usage/cost/token accounting, corrections and one absolute deadline are shared; model resolution is lazy and happens once at first ambiguity. The 128-candidate and 65,536-character limits are per binding. Explicit `tool_calls_limit` and `allow_direct=False` retain the existing agent route. Prefix effects may precede provider configuration failure; no rollback or durable cross-request resume is provided. This remains a partial milestone 3 feature, not milestone completion.

## Run

From the repository root, with the serving extra installed:

```sh
export MULTIPLE_CHOICE_DB="$PWD/orders.sqlite3"
uv run summonpot serve examples/13_multiple_producer_choices/app.py --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
curl -sS http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"category":"grocery","quantity":1,"idempotency_key":"demo-001"}'
```

The installed model selected by `SUMMONPOT_MODEL` handles the genuine grocery choices;
configure the provider/key required by that model. The endpoint itself never invents
catalog entries or receipts. The deterministic `stationery` category has no eligible
in-stock product and returns the framework's no-legal-choice conflict without an order.
The catalog includes a category with one product and one with multiple products; the
tea candidate has multiple delivery options, while coffee has one. `Product.product_id`
and `Delivery.product_id` are explicit canonical IDs, and persistence independently
rejects mismatched delivery IDs.

The keyless contract tests use a Pydantic AI `FunctionModel` solely to select among
real SQLite query results. That fixture is not a provider-quality test. The write operation
returns an existing receipt for the same key and identical selected order without another
stock deduction; reusing the key for a different order is rejected. A new HTTP request
still reruns both queries and choices. If stock or delivery availability changes, it may
fail before reaching the stored receipt, or select a different order and conflict.
This demonstrates write-level idempotency, not durable endpoint resume. Use a fresh
database path when repeating a demo, or inspect/reset the local database deliberately.
