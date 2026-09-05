# summonpot

summonpot modernizes APIs for AI without replacing the endpoint with a separate agent
layer. The endpoint remains the stable public abstraction while its contract combines
exact application behavior with explicitly bounded agentic decisions. You declare the
request model, the goal, the exact capabilities, and the response model.

One fully resolved `Exactly(1)` operation path executes without a model when the endpoint
uses a Pydantic request model and it has at least
one `FromRequest` binding, uses only `FromRequest` or immutable identity-stable callable
defaults, and the operation output is exactly the endpoint response model. All other declarations still use the provider-neutral agent
runtime. Broader multi-operation deterministic execution remains planned. The framework
owns execution, including any agent loop. **The ellipsis is a complete declaration body**,
not an implementation waiting to be written. Calling the decorated declaration directly is
rejected; execution goes through the served endpoint.

## The endpoint shape

```python
from pydantic import BaseModel, Field
from summonpot import Depends, Required, Summon

from my_service.operations import record_research, search_web


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3)
    depth: int = Field(default=3, ge=1, le=5)


class ResearchResponse(BaseModel):
    summary: str
    sources: list[str]


summon = Summon("my-service")


@summon("/research")
def research_topic(
    request: ResearchRequest,
    sources=Depends(search_web),
    receipt=Required(record_research),
) -> ResearchResponse:
    """Research this topic thoroughly and return a sourced report."""
    ...
```

Four parts, all load-bearing:

| Part | Becomes |
|---|---|
| Pydantic request model | the JSON body, its validation, and the OpenAPI input schema |
| docstring | the endpoint's goal — the agent's instructions |
| `Depends` / `Required` | the complete set of operations the agent may call |
| return model | the structured-output schema, validated locally before responding |

`Depends(op)` — the agent *may* call it. `Required(op)` — a final response is rejected
until it has completed successfully. Required use is checked from runtime state, not
asked for in the prompt.

## Do not write these

These are the mistakes to avoid, because they contradict the framework's model:

- **Do not implement the declaration body.** Use `...`. Business logic lives in the
  capabilities passed to `Depends`/`Required`.
- **Do not build an agent, chain, graph, or planner.** There is no agent object to
  configure. You declare an endpoint; the runtime owns whatever execution it needs.
- **Do not add an `action` field** to the request model. The endpoint's goal is fixed
  by its docstring; request JSON carries business data only.
- **Do not expose raw database sessions, engines, connections, cursors, or arbitrary
  SQL** as capabilities. Pass exact, prepared operations.

When upgrading a 0.5 project, replace legacy imports from `summonpot.pot`, application
variables named `pot`, and method-style endpoint registration with the `Summon`, `summon`,
and direct callable-application shape above. The CLI loads the module-level `summon`
variable exactly.

## Rules enforced at registration

summonpot raises when the application module is imported, not at request time. Each of
these is a hard error:

- **Every endpoint needs a docstring.** It is the goal, so it cannot be empty.
- **Paths start with `/`.**
- **One endpoint per `(path, method)`.** `GET /orders` and `POST /orders` may coexist;
  two `GET /orders` may not.
- **Annotations must resolve at runtime.** Under `from __future__ import annotations`,
  or with a quoted annotation, the name is looked up when the endpoint registers — so a
  `TYPE_CHECKING`-only import, or a model defined in a function scope that is no longer
  reachable, is rejected rather than silently degraded to an untyped body. A live class
  object passed directly as the annotation resolves fine. Declaring models at module
  scope and importing them normally avoids the question entirely.
- **Request declarations match the HTTP method.** Body-carrying methods may use
  individual body parameters or exactly one Pydantic request model. A Pydantic model
  must be the only request parameter; capability parameters are declaration-only and
  never become HTTP fields. Bodyless methods use individual scalar or
  sequences-of-scalars query parameters and reject Pydantic request models.
- **Capabilities must be callable and bound.** A plain function, a `functools.partial`,
  a bound method, or an object with `__call__`. An unbound method is rejected, because
  nothing can supply its receiver.
- **Capability names must be unique** within an endpoint.
- **`stream=True` is not implemented** and raises.

## Typed operation contracts

Use `Operation` when the source of each capability argument is part of the endpoint
contract. Keep these declarations beside the application operations, then reference the
complete contracts through `Depends` or `Required`:

```python
from my_service.models import Customer, OrderOption, OrderRequest, OrderResponse
from my_service.operations import find_options, load_customer, place_order
from summonpot import (
    AgentChoice,
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)


customer = Operation(
    load_customer,
    bind={"customer_id": FromRequest("customer_id")},
    output=Customer,
)
options = Operation(
    find_options,
    bind={"sku": FromRequest("sku")},
    output=list[OrderOption],
)
order = Operation(
    place_order,
    bind={
        "customer_id": FromResult(customer, "customer_id"),
        "option": AgentChoice(from_result=options, item_type=OrderOption),
        "actor_id": FromContext("actor_id"),
    },
    output=OrderResponse,
    after=(customer, options),
)

summon = Summon("order-api")


@summon("/orders")
def create_order(
    request: OrderRequest,
    customer_result=Required(customer),
    available_options=Required(options),
    order_result=Required(order),
) -> OrderResponse:
    """Place an order using one approved option."""
    ...
```

The argument sources mean:

| Source | Declaration |
|---|---|
| validated request field | `FromRequest("field")` |
| field from a declared producer's typed output | `FromResult(operation, "field")` |
| framework-owned context | `FromContext("key")` |
| direct or collection-backed model selection | `AgentChoice(...)` |

Once `bind=` is present, bind every argument that has no default. Registration rejects
unknown arguments, missing request or result fields, undeclared producers, unreadable
outputs, invalid `after=` references, and unsupported selectable collection shapes.
Dependency cycles are structurally unrepresentable through the immutable public
`Operation` API rather than discovered by a separate cycle detector.

Known source, element, and destination types must be compatible. The policy is to
**reject only provable incompatibility**: missing annotations, `Any`, context values, and
relationships that cannot be established remain unknown. An unknown branch does not
erase a known contradiction.

`output=` is required before another operation can use `FromResult` or collection-backed
`AgentChoice`. Bare callables and `Operation` declarations without `bind` remain valid;
in those cases the model chooses the arguments as before.

Call-bound helpers can refine a marker declaratively:

```python
from summonpot import AtMost, Depends, Exactly, Required

lookup = Depends(customer, calls=AtMost(2))
write = Required(order, calls=Exactly(1))
```

For one required typed operation with `calls=Exactly(1)`, the runtime enforces bindings
when every non-default argument uses `FromRequest` or direct `AgentChoice`: trusted and
defaulted arguments are hidden from the model, the only start is reserved before execution,
and `output=` is locally validated before satisfying `Required`. When the endpoint uses a
Pydantic request model, has at least one `FromRequest` binding, uses only `FromRequest`
or supported immutable callable defaults, and `output=` is exactly the endpoint response model, Summonpot executes it directly
without resolving or constructing a model. There is no model fallback after direct
execution begins. Multi-operation chains, `FromResult`, `FromContext`, `after`,
collection-backed choices, and broader call bounds remain registration-only. Unsupported
shapes keep the existing model-supplied argument behavior.

Runtime-enforced output schemas must not define a custom model `__init__`, including
nested models. Registration rejects that unsupported constructor path rather than
allowing it to bypass nested output validation. Use Pydantic model validators instead.

HTTP request validation runs once. The server transfers a detached, plan-bound validated
snapshot to the runtime rather than revalidating its JSON prompt representation. Raw
runtime inputs still undergo validation; ordinary request wrappers are not trusted.


Supported immutable callable defaults are exact built-in `None`, `bool`, `int`,
`float`, `complex`, `str`, and `bytes` values, plus tuples and frozensets containing
only those values recursively. Custom types (including subclasses of those built-ins)
and mutable defaults keep the endpoint agent-backed; copy hooks are not proof of
immutability. Scalar request declarations also remain agent-backed.

## HTTP methods

`method=` defaults to `POST`. `GET`, `DELETE` and `HEAD` carry no body, so their
parameters become **query-string parameters** and a Pydantic request model is rejected:

```python
from typing import Literal


@summon("/tickets", method="GET")
def list_tickets(
    status: Literal["open", "closed"] = "open",
    ids: list[int] | None = None,
) -> TicketPage:
    """List tickets matching the given status."""
    ...
```

Query parameters must be scalars or sequences of scalars. A mapping such as
`dict[str, int]` has no query encoding and is rejected — use `POST` for that.

## Path parameters

A `{name}` placeholder in a route binds from the URL, on **every** method including
the body-carrying ones. Each placeholder must match exactly one declared parameter,
and that parameter must be **required** and annotated with a scalar the URL can
carry: `str`, `int`, `float`, `bool` or `UUID`.

```python
from uuid import UUID


@summon("/customers/{customer_id}", method="POST")
def update_customer(customer_id: UUID, name: str) -> Customer:
    """Update one customer."""
    ...
```

A path parameter is **excluded from the generated request body model**, so the value
lives in exactly one place. The URL is its only authority: a body that also carries
`customer_id` does not override the URL segment.

When the URL owns *every* declared parameter, the route takes **no request body at
all** — call it with nothing but the path:

```python
@summon("/items/{item_id}", method="POST")
def touch_item(item_id: int) -> Item:
    """Touch one item."""
    ...
```

```bash
curl -X POST http://localhost:8000/items/7    # no -d, no Content-Type
```

These are rejected at registration, not at request time:

- a placeholder that no parameter is named after;
- the same placeholder named twice in one route;
- a path parameter with a default — the URL always supplies it, so it is never optional;
- a path parameter annotated with a non-scalar such as `list[int]` or a model. A
  structured value belongs in the body.

Because a Pydantic request-model endpoint takes exactly one request parameter, it
cannot also declare a path parameter; that signature is rejected already.

## Running it

Install the server, command-line, and chosen provider integrations explicitly. For
Anthropic:

```bash
pip install "summonpot[serve,cli,anthropic]"
```

`serve` installs FastAPI and uvicorn, `cli` installs the `summonpot` command, and the
provider extra installs that provider's client. Replace `anthropic` with the provider
named by your model.

For local development, bind explicitly to loopback:

```python
summon.serve(host="127.0.0.1", port=8000)
```

```bash
summonpot serve app.py --host 127.0.0.1 --port 8000  # variable: `summon`
```

`Summon.serve()` defaults to `0.0.0.0`, exposing the service on every network interface.
Endpoints do not include built-in authentication, and every reachable request can spend
provider credit. Use `host="127.0.0.1"` for local development. Before deliberately
exposing a service, put authentication in front of it and configure usage limits and a
timeout.

To run with no provider account at all — useful for checking routing, validation and
capability wiring before any key exists:

```bash
export SUMMONPOT_MODEL=test
```

An eligible single-operation deterministic endpoint requires no provider model or
credentials. The environment setting above is needed only when a declaration takes the
agent path.

Otherwise choose a provider-qualified model and set that provider's key:

```bash
export SUMMONPOT_MODEL=anthropic:claude-sonnet-4-5
export ANTHROPIC_API_KEY=...
```

## Bounding a call

An endpoint served against a configured provider spends the operator's credit on every
request, so cap it:

```python
from summonpot import Summon, UsageLimits
from summonpot.runtime import Runtime

summon = Summon(
    "my-service",
    runtime=Runtime(
        usage_limits=UsageLimits(request_limit=8, total_tokens_limit=40_000),
        timeout=30.0,
    ),
)
```

`Summon(model=...)` sets the default model instead; the two are mutually exclusive,
because a supplied runtime already carries its own.

The timeout releases the caller on the deadline, but it **cannot interrupt a
synchronous capability already running in a worker thread** — a write started before
the deadline still completes. Give such a capability its own internal deadline.

## Failure responses

| Status | Meaning |
|---|---|
| `422` | request failed validation against the declared models |
| `429` | the endpoint exceeded its configured usage limit |
| `502` | the model failed to satisfy the contract, or the provider failed |
| `504` | the endpoint exceeded its timeout |
| `500` | provider misconfiguration, or an error inside a capability |

Response bodies never carry model output or provider text; details go to the server log.

## Writing capabilities

A capability is an ordinary function. It runs for real — summonpot never replaces its
implementation.

```python
def search_web(query: str) -> list[str]:
    """Search approved sources for the query."""
    return client.search(query)
```

The docstring becomes the operation's description for the model, and the annotations
become its schema, so both are worth writing carefully.

Two things to know:

- **Synchronous capabilities run in a worker thread.** Do not capture a thread-affine
  resource such as a default SQLite connection; open one per call.
- **Argument authority depends on the declaration shape.** The enforced single-operation
  form hides `FromRequest` and defaulted arguments and exposes only `AgentChoice`. Bare
  capabilities and broader operation graphs still receive model-supplied arguments. A
  fully resolved exact-response operation runs directly; all other declarations use the
  agent path. Validate inputs and enforce authorization inside every capability.
