# 18. Bounded checkpoint cleanup (current source, unreleased)

One endpoint inspects a record, deterministically verifies its normalization rules,
discovers permitted corrections, applies a canonical selected correction, and persists
and reads back the final report. The five application operations do not call one
another. Summonpot owns all rounds and the response.

```bash
CHECKPOINT_CLEANUP_DB=/path/to/fresh-cleanup.sqlite3 \
SUMMONPOT_MODEL=openrouter:openai/gpt-4.1-mini \
uv run summonpot serve examples/18_checkpoint_cleanup/app.py --host 127.0.0.1 --port 8000

curl -sS localhost:8000/checkpoint-cleanup \
  -H 'content-type: application/json' -d '{"record_id":"needs-review"}'
```

Configure the chosen provider's credentials in the serving environment. Request JSON
contains only business record identity, never a framework action, model or mode.
Published v0.14.0 does not contain `until`; this example requires current source.

The strict `accepted` check allows up to three checks and two continuation rounds:

- `valid`: verified immediately, zero correction starts and no model resolution.
- `needs-review`: two normalizations permit verification; one singleton choice may
  resolve locally, with no extra model acknowledgment.
- `exhausted`: three independent defects cannot all be corrected within two starts;
  the application persists a truthful `unresolved` report, not invented approval.

All choices are safe normalizations in this application's data model. The fixed goal
expresses a preference order; application-produced candidates contain the exact
record/revision/action facts. The agent selects an opaque token, not an approval or
a replacement snapshot. The verifier alone determines acceptance.

SQLite operations use fixed parameterized queries. Correction writes compare the
selected revision. Terminal persistence compares the checked snapshot in the same
transaction that writes and reads the report. State, correction rows and reports
are real application effects. Default storage is under the user's cache directory;
seed rows use `INSERT OR IGNORE` and are never reset automatically.

A fresh request re-inspects current state. Stored correction rows are application
history, not framework aggregation, idempotency or durable resume. A later error or
cancellation can follow a committed correction or report; there is no rollback or
safe endpoint-wide retry promise. Use fresh database paths to reproduce seed cases.
