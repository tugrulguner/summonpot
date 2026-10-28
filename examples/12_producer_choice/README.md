# Producer-constrained inventory choice

This runnable example gives one fixed endpoint goal: find real in-stock SQLite inventory matching the request text, select one of those candidates, reserve one unit, and return the database-backed receipt. The request contains only business data (`query`, `order_id`, and `idempotency_key`); callers cannot choose an action or operation. The producer returns `list[Candidate]`; the consumer receives the exact canonical candidate selected through a request-local opaque token, not a model-authored object or identifier.

The order write uses a fresh SQLite connection per call and `BEGIN IMMEDIATE`. It verifies that the candidate's label, stock, and revision still match the producer snapshot before decrementing stock and inserting the order. The idempotency key is unique: a retry with the same order and item returns the stored receipt without another decrement; reusing it for a different order or item is rejected. A stale inventory candidate fails rather than reserving against outdated evidence. This two-step flow's unique terminal operation is the write itself, which returns the typed receipt persisted by that operation.

Choice domains are bounded by the runtime: an empty or over-128-item candidate list, or projected evidence over 65,536 characters, is unavailable and maps to HTTP 409 before the choice step. The example intentionally does not claim unbounded search, live provider credentials, or a live-provider test. Production runs use normal `SUMMONPOT_MODEL` configuration. The tests install a keyless scripted Pydantic AI `FunctionModel` solely to exercise the real runtime/tool schema/HTTP/SQLite path deterministically; it parses the candidate evidence and selects the requested matching candidate, rather than inventing a result.

## Execution boundary

Published v0.13.0 always uses the configured agent runtime for this producer-backed choice, including when a query yields a single candidate. Current source has an **unreleased** narrow optimization for a uniquely ordered required `Exactly(1)` chain with exactly one producer-backed `AgentChoice(from_result=...)` argument across the whole chain and no other choice. It still requires a Pydantic request, at least one `FromRequest` binding, supported immutable defaults and request/result/authenticated-context sources, an exact full terminal response annotation, and the producer before its consumer. Empty, unavailable, or oversized domains fail before model resolution or downstream work. A singleton is bound locally and its fully resolved suffix runs without a model. Two or more candidates trigger model resolution only after the resolved prefix; that run retains the existing agent-mediated suffix without replaying the prefix. Existing candidate/evidence limits remain 128 and 65,536 characters, including singleton domains. Prefix operations may have effects before a later provider configuration failure; there is no rollback claim. Other declarations keep their existing behavior.

## Run

From the repository root with Python 3.13 and the committed lockfile:

```sh
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv sync --locked --extra serve --extra cli --extra openai
export INVENTORY_DB="$PWD/inventory.sqlite3"
export OPENAI_API_KEY=...                         # configure your provider credential
export SUMMONPOT_MODEL=openai:gpt-4o-mini         # or another supported provider:model
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv run summonpot serve examples/12_producer_choice/app.py --host 127.0.0.1 --port 8000
```

In another terminal, submit business data (replace the idempotency key for a new order):

```sh
curl -sS -X POST http://127.0.0.1:8000/orders \
  -H 'content-type: application/json' \
  -d '{"query":"blue notebook","order_id":"order-2026-001","idempotency_key":"order-key-2026-001"}'
```

Independently verify the persisted row and stock change with SQLite:

```sh
sqlite3 "$INVENTORY_DB" \
  "SELECT order_id,idempotency_key,item_id,item_label,candidate_stock,candidate_revision,remaining_stock,status FROM orders WHERE order_id='order-2026-001';"
sqlite3 "$INVENTORY_DB" \
  "SELECT item_id,label,stock,revision FROM inventory WHERE item_id='B';"
```

Run the real-runtime HTTP example tests with the same locked environment:

```sh
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv run pytest tests/test_producer_choice_example.py -q
```
