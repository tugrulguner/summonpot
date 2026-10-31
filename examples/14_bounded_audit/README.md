# 14. Bounded SQLite audit

This source example demonstrates the unreleased bounded repeated-call contract on current
Summonpot source; it is not part of published v0.14.0. The endpoint's fixed goal asks
Summonpot to run one to three checks (`stock`, `prices`, or `deliveries`) and return the
canonical cumulative SQLite snapshot from the final successful invocation. The model
selects only a closed `Literal` check value. The request supplies the audit ID, while the
application owns all SQL, storage and per-check idempotency. There is no handler loop, raw
SQL capability, framework receipt, durable endpoint resume, or endpoint-wide transaction.

Use an isolated database path (recommended for development and tests):

```bash
export BOUNDED_AUDIT_DIR="$(mktemp -d)"
export BOUNDED_AUDIT_DB="$BOUNDED_AUDIT_DIR/bounded-audit.sqlite3"
export SUMMONPOT_MODEL="openrouter:openai/gpt-4.1-mini"
summonpot serve examples/14_bounded_audit/app.py --host 127.0.0.1 --port 8000
```

The default, when `BOUNDED_AUDIT_DB` is unset, is
`~/.cache/summonpot/bounded-audit.sqlite3`—never a database in the repository root. Seed
rows are inserted only when absent; existing records are not reset. Submit business data
only:

```bash
curl -X POST http://127.0.0.1:8000/audits \
  -H 'Content-Type: application/json' \
  -d '{"audit_id":"quarterly-2026-q4"}'
```

`audit_checks` has a unique `(audit_id, check_name)` key. Repeating a check for the same
audit returns the stored finding instead of writing it again. This is application-owned
write idempotency only: a repeated HTTP request is a new runtime run, not a resume, and
prior effects are not rolled back if a later call fails. Inspect the database independently
with SQLite; the returned `Snapshot` lists checks and findings persisted for that audit.
The endpoint exposes no application function as a provider function tool: the bounded
executor receives a private decision contract with safe fixed control/argument fields.

The example requires provider configuration for its model-selected checks. Its regression
tests use keyless `FunctionModel` responses to exercise runtime authority and SQLite state;
those tests do not evaluate provider decision quality.
