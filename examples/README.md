# Summonpot examples

Included from version 0.15.0 can omit `Operation.output` when the callable has a resolved
return annotation. Input bindings remain explicit. Earlier runnable examples retain explicit
outputs for compatibility with published v0.14.0; source users may omit the redundant
`output=CustomerRecord` in example 7 or `output=QuoteResponse` in example 8. This changes
neither example's application work nor execution purpose.

These examples grow from one typed endpoint to a multi-file service with bounded agentic orchestration. Every endpoint uses the same executable contract:

```text
request model + fixed docstring goal + declared capabilities + response model
```

The ellipsis is a complete declaration body, not an implementation waiting to be written:

```python
...
```

Summonpot never calls that body. Calling the decorated declaration directly raises an
error; serve the application or invoke the generated HTTP route.

## Before running

For a published installation, install the server and CLI extras and whichever provider integration you use. For OpenRouter:

```bash
pip install "summonpot[serve,cli,openrouter]"
export OPENROUTER_API_KEY='<your key>'
export SUMMONPOT_MODEL="openrouter:openai/gpt-4o-mini"
```

Examples 2, 4, and 6 use the configured agent runtime and require a working provider/model configuration; deterministic operations do not make their endpoints model-free. Levels 8, 9 checks, 10, 11, 13a authenticated-context, and a singleton level-12 candidate set can run without provider configuration on their eligible path. Ambiguous level-12 candidates and level-13 multiple-choice choices need model resolution; level 14 uses model-selected checks. Level 13 authenticated context still requires an application-owned bearer credential. Level 8's fully resolved operation requires no provider model or credentials. From 0.12.0,
the fully resolved chains in levels 10 and 11 also run without a model. Level 12 demonstrates
the producer-choice path. Its singleton local route is included from version 0.14.0; published
v0.13.0 ran all level-12 choices through the configured agent runtime.

For source development, use the committed environment below. The 13b and 14–22 lessons are also available in the v0.15.0 source distribution:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv sync --locked --all-extras
env -u PYTHONPATH -u VIRTUAL_ENV UV_PYTHON=3.13 uv run summonpot serve examples/basic_app.py --host 127.0.0.1 --port 8000
```

Keep secrets in your environment or secret manager—never in an example file. Start any example through the CLI:

```bash
summonpot serve examples/basic_app.py --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/docs` or call it with `curl`.

Bare `Depends(...)` and `Required(...)` capabilities still receive model-selected
arguments. The bound runtime is deliberately narrower: an endpoint with exactly one
required typed operation, `Exactly(1)`, and only `FromRequest`, authenticated `FromContext`
(from 0.13.0), direct `AgentChoice`, or
defaulted arguments receives trusted request injection, a filtered model schema, local
operation-output validation, and one permitted start. Level 7 runs that shipped path.
When the endpoint uses a Pydantic request model, the operation has at least one
`FromRequest` binding, resolves all inputs through `FromRequest`, authenticated `FromContext`
(from 0.13.0), or supported immutable callable defaults,
and its output exactly matches the endpoint response model, Summonpot executes it directly
without a model; Level 8 runs that path. Version 0.11.0 also admits a sequential `Required(..., calls=Exactly(1))` chain of two or more operations, with exactly one ready operation at every step, linked by `FromResult` or `after` and using `FromRequest`/`FromResult`, supported immutable defaults, and optionally producer-backed `AgentChoice(from_result=...)` from `list[ConcreteModel]`. At the historical v0.11.0 boundary, every supported chain executes through the agent runtime. The unique terminal operation output annotation must exactly match the endpoint response annotation; its canonical validated result is returned. `FromResult` implies readiness; optional `after` adds success-ordering. Intermediate canonical results are hidden from the model (completion acknowledgments only). Unsupported graphs fail closed. Sequential chain support starts in 0.11.0; historical v0.10.0 does not include it.

From 0.12.0, fully resolved chains run without a model only with a Pydantic request,
at least one `FromRequest` binding, two or more required `Exactly(1)` operations with
unique readiness, supported request/result/context sources or immutable defaults, and the
terminal operation's exact full endpoint response annotation. Published v0.13.0 kept every
producer-backed choice agent-mediated. Version 0.14.0 includes exactly one producer-backed
choice across the eligible chain: a singleton binds locally; multiple candidates hand off
after the prefix. Included from version 0.15.0 extends optimization eligibility to one or
more producer-backed choices. Summonpot checks all domains before each consumer starts,
progresses singleton choices locally, and asks a private selector with no business tools
only for ambiguous tokens. The shared invocation kernel continues the chain and returns
the canonical terminal result without a final model acknowledgment. Request/principal,
usage budget, reservations and deadline are shared; model resolution is lazy and once per
request. Per-binding limits remain 128 candidates and 65,536 evidence characters. Explicit
`tool_calls_limit`, `allow_direct=False`, and other noneligible declarations keep their
existing route. Prefix effects are not rolled back; no durable cross-request resume or
effect replay is added. This is a partial milestone 3 slice, not completion; historical
v0.14.0 remains exactly-one-choice. See the [full version 0.15.0 contract](../docs/declarative-capabilities.md#version-0150-framework-owned-decision-progression).
From 0.13.0, authenticated `FromContext` may also resolve inputs in those admitted direct
single-operation and chain paths. The Pydantic request, at least one `FromRequest`,
immutable-default, unique-readiness, and exact full response-annotation requirements
remain; context-only or scalar-request declarations and any declared `AgentChoice` remain
agent-mediated. Level 13 demonstrates that authenticated direct path.

## Version 0.15.0 bounded checkpoint progression

The public marker is `Required(check, calls=Between(1, M), until="accepted")`; it names a stored, non-null strict Boolean field, with required bounds `1..M` and optional negative-continuation bounds `0..M-1`. True closes; false continues, and the Mth false closes unresolved. An empty choice domain fails closed with the existing redacted 409, not an unresolved result. The request, context, invocation ledger, budget and deadline are shared. There is no rollback, replay, durable resume or recovery; a later failure does not undo effects. See the [checkpoint contract](../docs/checkpoint-progression.added.md). Published v0.14.0 does not include this behavior.

## Progression

Included from version 0.13.0: [authenticated tenant context](13_authenticated_context/README.md)
as level 13. It verifies application-owned bearer credentials and injects `FromContext`
without putting identity in caller JSON or model arguments. The SQLite example runs
model-free and independently verifies tenant-scoped writes and idempotency. Published
v0.12.0 does not include this context feature.

### 1. Minimal typed endpoint

File: `basic_app.py`

Shows a Pydantic request, fixed endpoint goal, and typed structured response without capabilities.

```bash
curl -X POST http://127.0.0.1:8000/review \
  -H 'Content-Type: application/json' \
  -d '{"text":"The setup was quick and the API is clear."}'
```

### 2. Required exact capability

File: `02_required_capability.py`

Shows `Required(...)`. The runtime rejects a final response until `calculate_quote` succeeds.

```bash
curl -X POST http://127.0.0.1:8000/quotes \
  -H 'Content-Type: application/json' \
  -d '{"unit_price_cents":1299,"quantity":3,"tax_rate_percent":"8.25"}'
```

This example wraps a bare callable in `Required(...)`, so it remains on the configured model
runtime. Level 8 shows the narrower typed `Operation` contract that qualifies for shipped
no-model execution.

### 3. Bounded agentic order fulfillment

File: `03_agentic_order.py`

Shows a bounded choice among `Depends(...)` capabilities followed by the required `create_order` write. The executor receives only these exact operations; it receives no filesystem, shell, database connection, or arbitrary code tool.

```bash
mkdir -p "$HOME/.cache/summonpot/examples"
export SUMMONPOT_ORDER_LOG="$HOME/.cache/summonpot/examples/order.jsonl"
summonpot serve examples/03_agentic_order.py --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"customer-7","sku":"red-mug","quantity":2,"allow_substitute":true}'
```

The endpoint checks inventory, may choose an approved substitute, and must call the order
write successfully before returning success. Its goal asks for exactly one write, but the
bare legacy capability form enforces required use rather than a maximum start count—so the write itself still
needs an idempotency policy.

### 4. HTTP methods and query parameters

File: `04_http_methods.py`

Shows GET and POST sharing `/products`. Route identity is the normalized `(path, method)` pair.

```bash
curl 'http://127.0.0.1:8000/products?category=stationery&max_price_cents=1500'

curl -X POST http://127.0.0.1:8000/products \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"customer-7","sku":"notebook"}'
```

Capability dependencies do not appear as request fields or OpenAPI parameters.

### 5. Bounded runtime and model override

File: `05_bounded_runtime.py`

Shows retries, usage limits, a request timeout, and a route-level model override.
`/summaries` uses `SUMMONPOT_MODEL`; `/summaries/fast` explicitly selects
`openrouter:openai/gpt-4o-mini`, using the same OpenRouter installation and key shown above.

```bash
curl -X POST http://127.0.0.1:8000/summaries \
  -H 'Content-Type: application/json' \
  -d '{"text":"Summonpot turns a typed endpoint declaration into an executable API while keeping its capability set closed.","max_sentences":2}'
```

Usage-limit, timeout, and provider failures are mapped to stable public HTTP errors while details remain in operator logs.

### 6. Multi-file support service

Directory: `06_support_service/`

Shows models, application operations, runtime configuration, and three bare legacy
capabilities split across normal Python modules.

Each `Required(fn)` uses its implicit marker bound and no explicit `Operation` contract, so
the provider-neutral agent runtime supplies arguments and the required-use gate demands one
successful call. Level 6 deliberately does not declare `FromRequest`, `FromResult`,
`AgentChoice`, `after`, or `Exactly(1)`: this example intentionally uses legacy declarations
with model-supplied arguments. Levels 7 and 8 introduce typed operation contracts; levels
10 and 11 show supported typed chains. Unsupported graphs are rejected at registration.

```bash
export SUMMONPOT_TICKET_LOG=/tmp/my-support-tickets.jsonl
summonpot serve examples/06_support_service/app.py --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/support \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"customer-1","message":"Our production API is unavailable in every region."}'
```

The CLI adds the application directory for normal local imports without putting it ahead of the standard library.

### 7. Enforced bound operation

File: `07_bound_operation.py`

Shows the first runtime-enforced typed operation contract. The validated request owns
`customer_id`; the model sees and chooses only `format`; Summonpot permits one start,
validates `CustomerRecord`, and only then satisfies `Required`.

```bash
summonpot serve examples/07_bound_operation.py --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/customers/view \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"customer-7"}'
```

This endpoint still uses the model to choose `format` and compose `CustomerView`.
Its declaration does not qualify for direct execution.

### 8. Single-operation deterministic execution

File: `08_direct_execution.py`

Shows the first no-model endpoint path. Every required operation argument comes from the
validated `QuoteRequest`, the operation is required exactly once, and its declared output
is exactly `QuoteResponse`. It therefore requires no provider model or credentials.

```bash
summonpot serve examples/08_direct_execution.py --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/quotes/direct \
  -H 'Content-Type: application/json' \
  -d '{"unit_price_cents":1299,"quantity":3,"tax_rate_percent":"8.25"}'
```

The response is computed by the exact application operation and validated as
`QuoteResponse`; Summonpot does not resolve or construct a model for this endpoint.

### 9. Contract boundary checks

Directory: `09_contract_boundaries/`

Shows the four hardening boundaries completed in 0.9.0: fail-closed registration for an
unsupported explicit contract, receiving-operation constraints checked before application
code starts, duplicate output namespaces rejected during registration, and matching raw
runtime and HTTP handling for aliases, defaults, and canonical typed values.

Run the credential-free checks directly:

```bash
python examples/09_contract_boundaries/checks.py
```

Then serve the same valid declaration and call it through HTTP:

```bash
summonpot serve examples/09_contract_boundaries/app.py --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/customers/view \
  -H 'Content-Type: application/json' \
  -d '{"customerId":"customer-7"}'
```

The operation requires a customer identifier of at least three characters even though the
request model accepts any nonempty identifier. The boundary check submits a shorter value
and verifies that the application operation never starts.

### 10. Sequential result chain

Directory: `10_result_chain/`

Demonstrates a two-operation sequential result chain and an application-owned SQLite inventory. The fully resolved path is model-free from 0.12.0; historical 0.11 chains were agent-mediated. The SQLite code is example application code, not a framework database adapter. Started, failed, or uncertain operations are never replayed in the same run; this does not promise rollback or exactly-once external effects. Cross-request retries require application idempotency.

Producer-backed `AgentChoice(from_result=...)` is limited to these sequential chains and
selects only from a successful producer's locally validated `list[ConcreteModel]`. It uses
bounded inert projections and opaque request-local tokens, not canonical result values or
full canonical-result context. Empty, unavailable, or oversized choice sets fail with a
fixed redacted 409 before model decision or downstream work.

### 11. Fully resolved linear result chain

Directory: [`11_linear_result_chain/`](11_linear_result_chain/)

Shows a three-operation, fully resolved SQLite reservation chain: read a snapshot, persist a reservation, then read and return the persisted receipt. The direct path is model-free from 0.12.0; application-level idempotency does not provide framework rollback or durable cross-request resume. See its guide for an independent SQLite query.

### 12. Producer-constrained inventory choice

Directory: [`12_producer_choice/`](12_producer_choice/)

Shows a producer-backed choice among validated SQLite inventory candidates, followed by a
write operation that verifies the producer snapshot and returns a persisted receipt. The
choice is locally token-bound to one canonical producer result. The tests exercise the
real runtime, HTTP, and SQLite path with a keyless scripted model; the example's production
run uses the configured provider.

### 13a. Authenticated tenant context (released in 0.13.0)

Directory: [`13_authenticated_context/`](13_authenticated_context/)

Shows application-owned bearer authentication, canonical `FromContext` bindings, tenant-scoped SQLite notes and independently checked persistence/idempotency. It runs model-free on the supported resolved path, but still requires the application-issued bearer credential. Summonpot does not provide login or infer tenant authority from caller JSON. See the [guide](13_authenticated_context/README.md).

### 13b. Multiple producer-backed choices (included from version 0.15.0)

Directory: [`13_multiple_producer_choices/`](13_multiple_producer_choices/)

Shows framework-owned progression across multiple producer-backed choice bindings in one eligible sequential chain. This is not part of the v0.14.0 release boundary. See the [execution boundary](13_multiple_producer_choices/README.md#execution-boundary).

### 14. Bounded repeated calls: audit (included from version 0.15.0)

Directory: `14_bounded_audit/`

The inventory audit demonstrates one required typed SQLite operation called sequentially within positive finite bounds (minimum at least one, maximum greater than one), with a Pydantic request, `FromRequest`, and closed string choices. Summonpot owns selection/finish; at maximum it returns the final successful canonical snapshot without another model acknowledgment. Any invocation failure aborts. The example's real SQLite operations and checks verify persisted findings. This is not an implicit batch or general graph, and it does not alter published v0.14.0. See the [unreleased contract](../docs/bounded-repeated-calls.added.md).

### 15. Repeated-stage final-result consumer (included from version 0.15.0)

Directory: [`15_repeated_stage/`](15_repeated_stage/)

Shows one bounded repeated producer closing before a choice-free terminal operation consumes its explicitly addressed final canonical result with `FromResult(..., invocation="final")`. This narrow source shape does not implement repeated consumers or an inspect/correct/verify workflow; published v0.14.0 is unchanged. See the [contract](../docs/repeated-stage-results.added.md).


### 16. Resolved preparation, repeated checks, verification and finalization (included from version 0.15.0)

Directory: [`16_stage_chain/`](16_stage_chain/)

Shows the version 0.15.0 single-stage chain without changing earlier examples. Order loading owns the request bindings; the repeated checks consume validated preparation results. Deterministic verification denies incomplete or failed checks before the final operation persists the report. The model owns only bounded check selection, not approval. This source extension is included from version 0.15.0 and is not in published v0.14.0.

### 17. Candidate selection followed by bounded checks (included from version 0.15.0)

Directory: [`17_choice_stage/`](17_choice_stage/)

Combines one application-backed supplier selection with bounded check selection, deterministic verification and a persisted canonical report. Selection identifies which supplier the checks and report concern. Empty candidates stop before checks; singleton selection needs no selection-model call, but the repeated checks still do. This source extension is not in published v0.14.0.


### 18. Bounded checkpoint cleanup (included from version 0.15.0)

Directory: [`18_checkpoint_cleanup/`](18_checkpoint_cleanup/)

Shows application-owned inspection, deterministic verification, permitted guarded correction, reinspection and revision-checked report persistence. Summonpot owns the bounded loop; the application has no handoff orchestration. `until="accepted"` is a stored strict Boolean: true closes; false permits continuation, and the Mth false closes unresolved without another continuation. It needs version 0.15.0; published v0.14.0 does not support it.

### 19. Bounded checkpoint status (included from version 0.15.0)

Directory: [`19_checkpoint_status/`](19_checkpoint_status/)

Shows the same rule in a three-operation declaration. Already-accepted state skips refresh and model resolution. Empty choice domains abort with the existing redacted 409, not an unresolved result. Writes may survive later failure; there is no rollback, effect replay, durable resume or recovery.

### 20. Fully resolved branch/join (included from version 0.15.0)

[Example 20](20_branch_join/README.md) demonstrates a deterministic subtotal branch and independent shipping calculation joining at one total-quote finalizer. This narrow version 0.15.0 path requires an acyclic, fully resolved required `Exactly(1)` graph with a unique sink reached by every operation and one exact response producer. It runs ready operations sequentially with declaration-order tie-breaking. It does not support `AgentChoice`, general graphs, or parallel execution; published v0.14.0 is unchanged.

### 21. URL path values and HTTP methods (included from version 0.15.0)

Directory: [`21_path_methods/`](21_path_methods/)

Shows typed URL-owned values across GET, POST, PUT, PATCH, DELETE and HEAD. GET consumes query data; POST/PUT/PATCH consume JSON; DELETE/HEAD need only the path. JSON cannot override the URL, and HEAD returns no HTTP body. These scalar declarations remain model-backed. The application is a truthful stateless transport demonstration, not a pretend CRUD store or persistence receipt. Its [guide](21_path_methods/README.md) distinguishes provider use from the keyless request-evidence fixtures used in tests.

### 22. Callable defaults and annotated contracts (included from version 0.15.0)

Directory: [`22_contract_defaults/`](22_contract_defaults/)

A real integer quote calculation keeps the immutable discount default application-owned while binding request values explicitly. The operation's tighter `Annotated` quantity constraint rejects an otherwise valid request before the callable starts. Its inferred full annotated output contract preserves response metadata and executes without a model. The [guide](22_contract_defaults/README.md) explains extra-field rejection, rounding and the v0.14.0 explicit-output alternative.

## What is intentionally not shown as shipped

The examples do not claim these planned features exist:

- general graphs and model-free execution outside the supported chain and narrow branch/join slices;
- SQLAlchemy or SQLite operation adapters;
- streaming responses;

Authenticated context is an application-owned credential hook, not built-in login or authorization.

For local development, bind to `127.0.0.1`. Before exposing a service, put authentication in front of it and configure runtime limits because every reachable request can spend provider credit.
