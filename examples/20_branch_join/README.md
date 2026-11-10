# Branch-and-join quote — included from version 0.15.0

Two independent exact calculations feed one final quote. The endpoint body is only `...`;
Summonpot derives readiness from `FromResult`. There is no public graph or hand-written
orchestration. This shape requires version 0.15.0 or later and is **not supported by published
v0.14.0**.

## Run

From a source checkout:

```bash
uv sync --all-extras --locked
uv run summonpot serve examples/20_branch_join/app.py --host 127.0.0.1 --port 8000
```

No provider configuration or credentials are required. Test the route:

```bash
curl -X POST http://127.0.0.1:8000/quotes/combined \
  -H 'Content-Type: application/json' \
  -d '{"unit_price_cents":1299,"quantity":3,"unit_weight_grams":250}'
```

The application computes the merchandise subtotal, applies its shipping tariff, and returns
`subtotal_cents`, `shipping_cents`, and their exact sum as `total_cents`. The tariff charges
499 cents for the first 500 grams and 199 cents for each additional started 500-gram block.
This is real deterministic application arithmetic, not a carrier quote, payment, inventory
reservation, or framework database adapter.

## What Summonpot owns

- `calculate_merchandise` and `calculate_shipping` bind only validated request fields.
- `combine_quote` consumes their locally validated result fields through `FromResult`.
- Every operation is `Required(..., calls=Exactly(1))`; the sole terminal owns the exact
  endpoint response contract.
- The terminal is deliberately declared first. Dependencies, not its signature position,
  determine when it may start. Among currently ready independent operations, declaration
  order is the stable tie-break: merchandise, shipping, then the ready terminal.
- Execution is sequential, not parallel. Add `after` if business logic requires additional
  ordering; missing dependency edges do not make side effects commutative or safe to run
  concurrently.
- The three return annotations supply omitted `output=` contracts at registration. Input
  sources remain explicit; the original declarations are not mutated.

There is no model lookup, model call, or model-authored final acknowledgment. Receiving and
output validation, one request deadline, start reservations and failure handling still use
the existing guarded kernel. A failure stops downstream work; no automatic replay,
rollback, durable recovery, conditional branches or agent-owned graph scheduling is added.

Earlier examples retain their teaching purpose and release compatibility. This example
adds the resolved branch-and-join lesson only.
