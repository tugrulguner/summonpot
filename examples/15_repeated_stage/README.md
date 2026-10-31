# 15. Repeated audit stage and final report

This example is for the current source checkout, not published summonpot 0.14.0. It
illustrates a bounded producer stage (one to three real inventory checks) followed by
exactly one required report operation. The model chooses only among the closed `stock`,
`prices`, and `deliveries` check names. Summonpot owns repetition, stage closure, explicit
`FromResult(..., invocation="final")` binding, and terminal invocation; the application
owns every SQL query, cumulative snapshot, and report write.

Run from the repository root after installing the locked all-extras development
environment (`uv sync --all-extras --locked`):

```bash
export REPEATED_STAGE_DB="$HOME/.cache/summonpot/repeated-stage-demo.sqlite3"
export SUMMONPOT_MODEL="openrouter:openai/gpt-4.1-mini"
uv run summonpot serve examples/15_repeated_stage/app.py --host 127.0.0.1 --port 8000
```

The default database is `~/.cache/summonpot/repeated-stage.sqlite3`; set
`REPEATED_STAGE_DB` to isolate runs. Initialization uses `CREATE TABLE IF NOT EXISTS` and
`INSERT OR IGNORE` for fixed seed rows. It does not reset prior state. The configured
provider must be available; this example does not guarantee which checks a real model will
select.

Send business data only—there is no caller-selected action or execution mode:

```bash
curl -sS -X POST http://127.0.0.1:8000/audits \
  -H 'Content-Type: application/json' \
  -d '{"audit_id":"demo-q4-2026"}'
```

Independently inspect the canonical terminal report and its source check rows:

```bash
sqlite3 "$REPEATED_STAGE_DB" \
  "SELECT audit_id, report_json FROM audit_reports WHERE audit_id='demo-q4-2026';"
sqlite3 "$REPEATED_STAGE_DB" \
  "SELECT check_name, anomaly_count, details_json FROM audit_checks WHERE audit_id='demo-q4-2026' ORDER BY check_name;"
```

Each producer call runs its selected fixed SQL query, upserts that finding under
`(audit_id, check_name)`, and returns a snapshot containing all findings persisted so far.
That cumulative snapshot is application behavior, not framework aggregation. The
terminal operation receives fields from the final successful producer invocation, builds
and persists the typed report, reads the stored payload back, and returns that actual
report. The audit ID is the application's report-write idempotency key; this does not
provide endpoint-wide exactly-once behavior or framework resume.

The producer and terminal use separate SQLite transactions/connections. If an invocation
or report write fails after an earlier check committed, those earlier rows remain; there is
no cross-operation transaction, rollback, replay, or durable resume. A successful report
covers only checks recorded for that audit, not unchecked inventory facts. Tests exercise
the current runtime with a keyless `FunctionModel`; they do not establish real-provider
selection quality.
