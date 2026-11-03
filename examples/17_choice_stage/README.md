# 17. Choose one supplier, then run bounded checks

This separate example demonstrates one supplier selection before one bounded repeated
stage: the application queries real supplier rows, the model selects one canonical
candidate, and the endpoint runs closed stock/price checks before verification and report
persistence. The fixed goal selects the lowest-price permitted candidate, then runs both
checks. Separate application operations verify current business facts and persist an
approval or denial; the model is not an approval authority. Failed checks do not cause
automatic reselection. The request contains only the category and
review identifier, never an action, mode, or execution selector.

This targets the current source checkout and is not a claim about published summonpot
0.14.0. The response is the canonical JSON report read back from SQLite. Check rows are
application-owned state rather than framework aggregation. A fresh request starts a fresh
run and can select again; there is no framework-wide idempotency, rollback, or durable
resume guarantee.

From the repository root with the locked development environment installed:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv sync --all-extras --locked
export CHOICE_STAGE_DB="$HOME/.cache/summonpot/supplier-review-demo.sqlite3"
export SUMMONPOT_MODEL="openrouter:openai/gpt-4.1-mini"
uv run summonpot serve examples/17_choice_stage/app.py --host 127.0.0.1 --port 8000
```

The database defaults to `~/.cache/summonpot/choice-stage.sqlite3`. Initialization
creates application-owned tables and inserts fixed supplier facts with `INSERT OR IGNORE`;
it does not reset existing state. In category `paper`, Northstar Supply has stock 42 and
costs 825 cents, while Maple Wholesale has stock 0 and costs 975 cents. Only Northstar
passes both checks. The `office` category is a singleton; an unknown category has no
candidates.

```bash
curl -sS -X POST http://127.0.0.1:8000/supplier-reviews \
  -H 'Content-Type: application/json' \
  -d '{"category":"paper","review_id":"demo-paper-1"}'
```

Read back the actual report and check effects independently:

```bash
sqlite3 "$CHOICE_STAGE_DB" \
  "SELECT report_json FROM review_reports WHERE review_id='demo-paper-1';"
sqlite3 "$CHOICE_STAGE_DB" \
  "SELECT supplier_id, check_name, passed, observed FROM review_checks WHERE review_id='demo-paper-1' ORDER BY supplier_id, check_name;"
```

The repeated stage accepts only `stock` and `prices` and can invoke at most three times;
verification requires both distinct checks, rechecks current facts, and persists `approved: false` for incomplete or failed reviews. All
queries are fixed and parameterized, and effects are keyed by review and selected supplier.
Each operation manages and closes its own SQLite connection; earlier committed checks
remain if a later phase fails. This does not provide a cross-operation transaction. The
keyless scripted tests exercise runtime enforcement and selected-supplier effect routing,
not real-provider selection quality.
