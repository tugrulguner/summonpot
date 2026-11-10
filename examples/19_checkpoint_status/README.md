# 19. Bounded checkpoint status (included from version 0.15.0)

This three-operation endpoint uses the same checkpoint rule as the longer cleanup
example: read actual progress, refresh only after a negative check, then persist the
closed check's report. There is no dedicated inspection or candidate-discovery role.
The body remains a declaration; the application contains no orchestration loop.

```bash
CHECKPOINT_STATUS_DB=/path/to/fresh-status.sqlite3 \
SUMMONPOT_MODEL=openrouter:openai/gpt-4.1-mini \
uv run summonpot serve examples/19_checkpoint_status/app.py --host 127.0.0.1 --port 8000

curl -sS localhost:8000/checkpoint-status \
  -H 'content-type: application/json' -d '{"job_id":"pending"}'
```

Configure the chosen provider's credentials in the serving environment. Request JSON
contains only job identity. Published v0.14.0 does not support this new declaration.

Seeded cases:

- `complete`: terminal verified report with no refresh or model resolution.
- `pending`: two normal-paced refreshes reach the target; the final report records
  the actual completed work and revision.
- `exhausted`: even two accelerated refreshes cannot reach its target; the bounded
  run persists `unresolved`. Reaching the start limit is not evidence of completion.

`normal` and `accelerated` are closed permitted argument values. The fixed endpoint
goal prefers normal pace; the agent cannot approve or request framework finish.
`until="accepted"` reads a locally validated strict Boolean. A maximum of three
checks permits at most two refresh starts, with one shared run budget/deadline.

Fixed parameterized SQLite statements record real refreshes. The application guards
revision when refreshing and checks the entire final snapshot in the same transaction
that persists/reads the report. Seed data is idempotent, never reset on import or a
new request. Default storage is a user cache path; use a fresh configured database
for repeatable seed demonstrations.

A new HTTP request starts fresh against current state; it is not a resume or an
exactly-once request. Writes may survive later failure or cancellation. No framework
rollback, recovery or transaction across all operations is implied.
