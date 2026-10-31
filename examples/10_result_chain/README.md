# Sequential result chain: inventory reservation

A small real service: the first required operation reads the requested SKU and its current revision from SQLite; the second receives that validated snapshot via `FromResult`, uses the request's idempotency key, and commits inventory plus a canonical reservation receipt in application-owned SQLite code. `FromResult` establishes readiness itself; the optional `after` declaration also states success ordering explicitly. The terminal operation's output model is the endpoint's exact response model.

## Run it

From the repository root (Python 3.11–3.14 and `uv` installed). The eligible fully resolved chain is model-free from 0.12.0; historical v0.11.0 chains ran through the agent runtime:

```sh
uv sync --locked --extra serve --extra cli
export INVENTORY_DB="$PWD/inventory.sqlite3"
uv run summonpot serve examples/10_result_chain/app.py --host 127.0.0.1 --port 8000
```

Then call the endpoint:

```sh
curl -sS -X POST http://127.0.0.1:8000/reservations \
  -H 'content-type: application/json' \
  -d '{"sku":"notebook","quantity":2,"idempotency_key":"order-2026-001"}'
```

Inspect persisted canonical data independently of the HTTP response:

```sh
sqlite3 "$INVENTORY_DB" \
  "SELECT idempotency_key, sku, quantity, inventory_revision, remaining, status FROM reservations WHERE idempotency_key='order-2026-001';"
```

A replay with the same key and same SKU/quantity returns the original persisted receipt. Reusing that key for different reservation data fails. A process/model failure after SQLite commits does not roll the write back; retry with the same key to recover the persisted receipt.

`FunctionModel` is used only in tests. It is not configured by this runnable example; production model selection uses `SUMMONPOT_MODEL`/Summonpot's normal runtime configuration.
