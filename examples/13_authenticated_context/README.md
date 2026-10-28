# Authenticated tenant context

A real HTTP bearer authenticator resolves tenant identity from app-owned `TENANT_BEARER_TOKENS` (`tenant-a:tokenA,tenant-b:tokenB`). Supply your own random secrets; do not put real tokens in source control or chat. No login, JWT, or token store is involved. Each note write uses its own SQLite connection, a tenant-scoped idempotency constraint, and returns a validated receipt read from/confirmed by SQLite. Repeating the same key and exact note data returns its persisted receipt; conflicting reuse fails. Caller JSON is strict (`extra='forbid'`) and cannot supply tenant identity.

Replays return the identical persisted creation receipt, including `status="created"`;
that status does not mean another row was inserted. Conflicting key reuse raises an
application `ValueError`, mapped by the existing runtime to a fixed redacted HTTP 500,
without changing the stored row. This example does not add a typed HTTP conflict mapping.

## Run

Authenticated `FromContext` is included from version 0.13.0; historical v0.12.0 does not include it. From the repository root,
install the locked serving/CLI environment before running the example:

```sh
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv sync --locked --extra serve --extra cli
export TENANT_BEARER_TOKENS='tenant-a:REPLACE_WITH_RANDOM_SECRET_A,tenant-b:REPLACE_WITH_RANDOM_SECRET_B'
export AUTH_CONTEXT_DB="$HOME/.local/share/summonpot-auth-context/notes.sqlite3"
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv run summonpot serve examples/13_authenticated_context/app.py --host 127.0.0.1 --port 8000
```

Use secrets generated locally (for example `python -c 'import secrets; print(secrets.token_urlsafe(32))'`). The shell environment is the credential source, not this documentation. In another terminal, substitute the configured token locally:

```sh
curl -i -X POST http://127.0.0.1:8000/notes \
  -H 'content-type: application/json' -H 'authorization: Bearer YOUR_CONFIGURED_TOKEN' \
  -d '{"note_id":"n-001","text":"First tenant note","idempotency_key":"key-001"}'
curl -i -X POST http://127.0.0.1:8000/notes -H 'content-type: application/json' \
  -d '{"note_id":"n-unauthorized","text":"must not persist","idempotency_key":"key-x"}'
```

Missing and invalid bearer credentials receive HTTP 401. Send the second tenant's configured token to create its independent note. Independently inspect persistence and tenant separation with SQLite:

```sh
sqlite3 "$AUTH_CONTEXT_DB" 'SELECT tenant_id,note_id,text,idempotency_key FROM notes ORDER BY tenant_id,note_id;'
```

The principal is app-authenticated, validated, frozen, and bound only through `FromContext`; neither request JSON nor model output controls tenant identity. The endpoint declares the operation and contains no handler logic. This direct request/operation/terminal-response path is model-free. Operation connections are acquired inside the worker function, not captured from startup. Authentication is synchronous, uses constant-time comparison for each configured token, and reveals no credential detail. The framework applies its runtime deadline to provider execution; as with any operation, a timed-out write may have committed before cancellation, so use the idempotency key to safely retry. A cross-tenant note identifier is not queried or disclosed: primary keys and retries are tenant-scoped.
