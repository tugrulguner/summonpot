# 16. Resolved order-review stage

This is a new source-checkout example, not a claim about published summonpot 0.14.0 or a PyPI release. It composes one request-bound order load, a one-to-three-call closed `stock`/`prices` stage, a deterministic verification operation, and a terminal SQLite JSON report write. The request binding is in the prefix; the repeated operation consumes only prefix results plus its direct literal `AgentChoice`.

From the repository root, install the locked all-extras environment and choose an isolated database:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv sync --all-extras --locked
export STAGE_CHAIN_DB="$HOME/.cache/summonpot/examples/order-review.sqlite3"
export SUMMONPOT_MODEL="openrouter:openai/gpt-4.1-mini"
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv run summonpot serve examples/16_stage_chain/app.py --host 127.0.0.1 --port 8000
```

The provider is resolved lazily when the endpoint reaches the repeated stage, after the prefix has loaded the order. Prefix effects are not rolled back if provider configuration fails. Repeated calls share the runtime's request-wide usage budget and deadline; the finite count bound does not replace those limits. There is no framework loop substitute, whole-endpoint transaction, durable resume, or endpoint-wide idempotency guarantee.

Send only the order identifier; the fixed endpoint goal is to review it:

```bash
curl -sS -X POST http://127.0.0.1:8000/reviews \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"order-valid"}'
```

The seeded `order-valid` satisfies both checks. `order-stock-fail` requests more units than the seeded stock and cannot be approved, even if its price check passes. Seed rows use `INSERT OR IGNORE`; initialization does not reset a database. Each operation opens its own SQLite connection/transaction and SQL uses fixed statements with bound parameters.

The application stores check rows cumulatively by review ID; this is application-owned state, not framework aggregation. Verification compares actual persisted check outcomes against current stock/price facts and requires the complete expected set. If the model finishes early, verification returns `approved: false` for missing checks rather than inferring approval. Repeated identical choices do not stand for additional checks. The final operation persists JSON, reads the canonical row back, and returns that retrieved report.

Inspect the actual effects independently:

```bash
sqlite3 "$STAGE_CHAIN_DB" "SELECT review_id, report_json FROM review_reports ORDER BY review_id;"
sqlite3 "$STAGE_CHAIN_DB" "SELECT review_id, check_name, passed, detail FROM review_checks ORDER BY review_id, check_name;"
```

Tests use the actual runtime and a keyless scripted `FunctionModel` to exercise selected checks and early finish. They establish orchestration behavior, not real-provider selection quality.
