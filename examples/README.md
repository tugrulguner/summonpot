# Summonpot examples

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

Install Summonpot with the provider and server extras you need. For OpenRouter:

```bash
pip install "summonpot[serve,cli,openrouter]"
export OPENROUTER_API_KEY='<your key>'
export SUMMONPOT_MODEL="openrouter:google/gemini-3.7-flash"
```

Level 8's fully resolved operation requires no provider model or credentials. The other
examples use the configured agent runtime.

Keep secrets in your environment or secret manager—never in an example file. Start any example through the CLI:

```bash
summonpot serve examples/basic_app.py --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/docs` or call it with `curl`.

Bare `Depends(...)` and `Required(...)` capabilities still receive model-selected
arguments. The bound runtime is deliberately narrower: an endpoint with exactly one
required typed operation, `Exactly(1)`, and only `FromRequest`, direct `AgentChoice`, or
defaulted arguments receives trusted request injection, a filtered model schema, local
operation-output validation, and one permitted start. Level 7 runs that shipped path.
When the endpoint uses a Pydantic request model, the operation has at least one
`FromRequest` binding, uses only `FromRequest` or supported immutable callable defaults,
and its output exactly matches the endpoint response model, Summonpot executes it directly without a model; Level 8 runs that path. Level 6
retains the broader multi-operation declarations that remain registration-only.

## Progression

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
export SUMMONPOT_ORDER_LOG=/tmp/my-orders.jsonl
summonpot serve examples/03_agentic_order.py --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"customer-7","sku":"red-mug","quantity":2,"allow_substitute":true}'
```

The endpoint checks inventory, may choose an approved substitute, and must call the order
write successfully before returning success. Its goal asks for exactly one write, but the
current runtime enforces required use—not the declared maximum—so the write itself still
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

Shows models, application operations, runtime configuration, and a typed operation chain
split across normal Python modules:

- `FromRequest` declares the customer lookup's request-field source;
- `FromResult` declares the ticket's dependency on the typed customer result;
- `AgentChoice` marks policy, priority, and summary values that remain model-selected;
- `after` records ordering, and `Exactly(1)` records the intended write bound.

These declarations are validated and stored when the module imports. The current runtime
does not inject bound values or enforce `after` and maximum/exact call counts yet; the model
still supplies capability arguments, while `Required(...)` enforces successful use at
least once. This example therefore demonstrates the shipped contract and registration
boundary without claiming the planned capability-graph executor already exists.

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

## What is intentionally not shown as shipped

The examples do not claim these planned features exist:

- multi-operation deterministic endpoint execution;
- SQLAlchemy or SQLite operation adapters;
- streaming responses;
- built-in authentication.

For local development, bind to `127.0.0.1`. Before exposing a service, put authentication in front of it and configure runtime limits because every reachable request can spend provider credit.
