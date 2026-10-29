# summonpot

summonpot modernizes APIs for AI without replacing the endpoint with a separate agent
layer. The endpoint remains the stable public abstraction while its contract combines
exact application behavior with explicitly bounded agentic decisions. You declare the
request model, the goal, the exact capabilities, and the response model.

One fully resolved `Exactly(1)` operation path, with the operation required as the sole declared capability,
executes without a model when the endpoint uses a Pydantic request model, has at least one
`FromRequest` binding, and resolves every input through `FromRequest`, authenticated
`FromContext` (from version 0.13.0), or supported immutable identity-stable callable defaults.
The operation output is exactly the endpoint response model, including its full annotated
contract. Uniquely ordered sequential required `Exactly(1)` chains also execute without a
model with the same Pydantic request and at-least-one-`FromRequest` requirements, all inputs
resolved through request/result/authenticated-context bindings or supported immutable
defaults, and an exact full terminal output annotation matching the endpoint response.
Context-only and scalar-request declarations remain agent-mediated, as does any direct
`AgentChoice`. Published v0.13.0 chains with producer-backed `AgentChoice` remained agent-mediated, even for a singleton. Included from version 0.14.0 is a narrow result-dependent route: an existing uniquely ordered chain of required `Exactly(1)` operations, Pydantic request with at least one `FromRequest`, exactly one producer-backed choice argument across the whole chain and no other choice, supported immutable defaults and request/result/authenticated-context bindings, and exact full terminal annotation. Empty/unavailable/oversized domains fail before model/downstream; singleton binds the canonical validated item locally and runs the suffix without a model; two or more candidates resolve the model only after the prefix and retain the existing agent-mediated suffix, without replay. The 128-item/65,536-character evidence limits remain on all paths. Other producer choices keep their existing agent route. Prefix effects may occur before a later provider-configuration failure; no rollback is implied. Bare legacy capabilities still use the provider-neutral agent runtime. Unsupported explicit contracts are rejected before serving. Version 0.11.0 supports sequential chains with exactly one ready operation at each step; that release's chains are agent-mediated. From version 0.12.0, fully resolved uniquely ordered chains run model-free; chains with agent-owned choices remain agent-mediated. Broader multi-operation deterministic execution and graph execution remain planned. Historical v0.10.0 does not include the 0.11.0 agent-mediated chain either.
The framework
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
| docstring | the fixed execution goal; on the agent path, the agent's instructions |
| `Depends` / `Required` | the complete set of operations available to execution |
| return model | the final local validator; on the agent path, the structured-output schema |

`Annotated[RequestModel, ...]` and `Annotated[ResponseModel, ...]` keep their Pydantic
metadata through runtime validation and the generated OpenAPI request/response schemas.
Response validators run during runtime validation, not again during HTTP serialization;
the transport preserves the registered serializers and inert output-storage audit.
Use these annotations when attaching constraints or schema descriptions; the underlying
models remain available through endpoint inspection. Direct execution requires the exact
response annotation, including its metadata, as the operation output contract. Business
parameters named `self` or `cls` remain ordinary request fields; unbound endpoint methods
are rejected rather than hiding a receiver.

`Depends(op)` makes an operation available to execution. On the agent-backed path, the
agent *may* call it. `Required(op)` rejects a final response until the operation has
completed successfully. Required use is checked from runtime state, not asked for in the
prompt.

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
- **Every route receives a stable OpenAPI `operationId`.** It is derived from the endpoint
  function name and HTTP method. Two routes that would produce the same ID are rejected
  during registration.
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
contract. The currently admitted shape is one required operation with `calls=Exactly(1)`,
a declared output, no ordering, and complete `FromRequest` or direct `AgentChoice` bindings:

```python
from my_service.models import Customer, OrderRequest, OrderResponse
from my_service.operations import load_customer
from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    Operation,
    Required,
    Summon,
)


customer = Operation(
    load_customer,
    bind={
        "customer_id": FromRequest("customer_id"),
        "format": AgentChoice(),
    },
    output=Customer,
)

summon = Summon("order-api")


@summon("/orders")
def create_order(
    request: OrderRequest,
    customer_result=Required(customer, calls=Exactly(1)),
) -> OrderResponse:
    """Load the customer and return the approved response."""
    ...
```

The argument sources mean:

| Source | Declaration |
|---|---|
| validated request field | `FromRequest("field")` |
| field from a declared producer's typed output | `FromResult(operation, "field")` |
| framework-owned context | `FromContext("key")` |
| direct or collection-backed model selection | `AgentChoice(...)` |

`FromResult` and `after` are enforced in a sequential chain of two or more operations from 0.11.0, provided exactly one operation is ready at each step. Such a chain may also use `AgentChoice(from_result=producer)` to choose from a producer's locally validated list of concrete Pydantic models.
`FromResult` itself establishes producer readiness; `after` independently requires
successful predecessor completion. From version 0.12.0, fully resolved chains run model-free only with a Pydantic request,
at least one `FromRequest` binding, a unique required `Exactly(1)` sequence, only
`FromRequest`/`FromResult` bindings or supported immutable callable defaults, and the
terminal operation's exact full endpoint response annotation. Its validated terminal result
is returned unchanged. In published v0.13.0, any `AgentChoice` keeps its chain agent-mediated. The narrow result-dependent exception above applies only to one producer-backed choice in the otherwise eligible chain; all other choices remain agent-mediated. Historical v0.11.0 chains
remain agent-mediated. Their unique terminal operation's full output
annotation must exactly equal the endpoint response annotation. Summonpot returns the
canonical validated terminal result, not model-authored claims. Intermediate canonical
results stay hidden from the model. Tool results are completion acknowledgments;
producer-backed choice arguments separately disclose bounded inert candidate evidence.
Collection-backed choices are supported only in these sequential chains, require a
declared producer with `output=list[ConcreteModel]`, and accept at most 128 candidates
and 65,536 JSON characters per binding. The model receives opaque request-local tokens
and inert projected candidate descriptions, not canonical result objects or full
canonical result context. The selected token is mapped locally to that exact canonical
validated member; Python equality is not authority. Projection respects field exclusions
and aliases without application serializers. Empty, unavailable, or oversized
sets fail with a fixed redacted 409 before model decision and before downstream work;
there is no extra model request. `FromContext` is supported only in the narrow authenticated-context slice described below, included from version 0.13.0. Unsupported graphs
fail closed. A two-or-more candidate choice still uses the agent runtime; it is not a
model-free execution path.

Binding sources must be exact built-in source types; subclasses are rejected. Once
`bind=` is present, bind every argument that has no default. Registration rejects
unknown arguments, missing request or result fields, undeclared producers, unreadable
outputs, invalid `after=` references, and unsupported selectable collection shapes.
Dependency cycles are structurally unrepresentable through the immutable public
`Operation` API rather than discovered by a separate cycle detector.

Known source, element, and destination types must be compatible. The policy is to
**reject only provable incompatibility**: missing annotations, `Any`, context values, and
relationships that cannot be established remain unknown. An unknown branch does not
erase a known contradiction.

`output=` is required before another operation can use `FromResult` or collection-backed
`AgentChoice`. Bare callable dependencies without an explicit contract remain valid and use
the legacy model-chosen argument path. `Operation(fn)` is still an explicit contract. It and
any other incomplete or unsupported `Operation` are rejected rather than silently downgraded.

Call-bound helpers can refine a marker declaratively:

```python
from summonpot import Exactly, Required

lookup = Required(customer, calls=Exactly(1))
```

For one required typed operation with `calls=Exactly(1)`, the runtime enforces bindings
when every non-default argument uses `FromRequest` or direct `AgentChoice`: trusted and
defaulted arguments are hidden from the model, the only start is reserved before execution,
and `output=` is locally validated before satisfying `Required`. When the endpoint uses a
Pydantic request model, has at least one `FromRequest` binding, uses only `FromRequest`
or supported immutable callable defaults, and `output=` is exactly the endpoint response model, Summonpot executes it directly
without resolving or constructing a model. There is no model fallback after direct
execution begins. Multi-operation chains are admitted only as a supported sequential chain: two or more required `Exactly(1)` operations connected by `FromResult` or `after`, using
`FromRequest`/`FromResult` and supported immutable callable defaults. These fully resolved
chains run without model resolution and return the unique terminal operation's canonical
validated result; a producer-backed `AgentChoice` keeps its chain agent-mediated.
`FromContext` outside the supported narrow shapes, unsupported choice containers, broader bounds and unsupported graphs are
rejected during registration. Direct `AgentChoice` remains supported in the existing
single-operation form. Bare `Depends(fn)` and `Required(fn)` calls keep their implicit
legacy bounds; explicit unsupported call bounds are not admitted.

For the chain, call maxima count starts and required minima count locally validated
successes. Failed, cancelled, or uncertain starts retain their reservations; model retries
never replay them. This is not rollback or distributed exactly-once execution. Applications
must implement cross-request idempotency, as the inventory example does.

For both direct and agent-backed execution in that supported slice, an injected
`FromRequest` value must satisfy its receiving operation parameter, including `Annotated`
primitive constraints, strictly before application code starts. Validation is noncoercive:
a broad request field does not authorize a narrower operation argument. A valid canonical
validated request value is passed unchanged, not replaced by a coerced value, and the check
does not rerun request-model validators.

The supported receiver vocabulary is exact primitive types with common non-transforming
numeric constraints and non-pattern string constraints, primitive `Literal` values with
exact-type semantics, unions when any branch safely matches, recursively checked built-in
containers, and structurally checked Pydantic model instances. The predicate uses unbound
built-in container operations, does not rebuild sets or dictionaries, and never calls a
serializer. Receiver models with typed `extra="allow"` fields have those extras checked
structurally too. Bare Decimal receivers require finite values before bounds or
`multiple_of` are checked. Decimal `allow_inf_nan=True`, float `multiple_of`, enum receiver
contracts, callable discriminators, and string `pattern` constraints are rejected at
registration because the hook-free predicate cannot reproduce their semantics exactly;
non-pattern string constraints remain supported. Integer and finite Decimal `multiple_of`
constraints remain supported. Receiver schemas containing custom functional validators
(`BeforeValidator`, `AfterValidator`, `WrapValidator`, or `PlainValidator`), transforming
string constraints, custom literal values, custom instance-checking metaclasses, or
unsupported core schemas are rejected at registration rather than silently stripped.

Runtime-enforced output schemas must not define a custom model `__init__`, including
nested models. Registration rejects that unsupported constructor path rather than
allowing it to bypass nested output validation. Use Pydantic model validators instead.

Output object keys must be unambiguous. Registration checks aliases, serialization aliases,
or computed fields in their respective namespaces for every endpoint response model and every
declared operation `output=` shape, including unsupported and multi-operation runtime shapes.
Enabled direct validation aliases cannot claim the same input key under the model's configured
validation policy; declared fields,
serialization aliases, and computed fields cannot emit the same JSON key, including inside
nested models, dataclasses, and typed dictionaries. This admission does not provide runtime
structural validation for broader graphs, whose execution remains unsupported. For a model with
`extra="allow"` on a runtime-enforced path, validation rejects an extra from an instance or
raw mapping after construction if it shadows a canonical field name or emitted alias, while
preserving and validating noncolliding extras. The check does not invoke application
serializers, copy hooks, `repr`, or `str`.

HTTP request validation runs once. The adapter transfers a private, plan-bound validated
value graph to the runtime rather than revalidating its JSON prompt representation or
calling application-defined copy hooks. Mutable compatibility views cannot change bound
operation inputs, and consumed transports cannot be replayed through request defaults.
Compatibility projection preserves exact built-in JSON scalars and dictionaries with exact
string keys. Exact list, tuple, set, and frozenset containers are recursively detached;
typed views preserve their native kind when projected members remain safely hashable, while
prompts receive JSON arrays. Hashed containers whose projected members are not hashable use
the inert `"<unavailable>"` fallback instead of invoking application hash/equality hooks.
Pydantic model values are projected from declared field storage, including aliases and
supported nested values, without calling model serializers or representation hooks.
Exact UUID, date, datetime, time, timedelta,
Decimal, and bytes values remain usable: prompts receive framework-safe strings and
custom-runtime typed views retain native values, with UUIDs independently reconstructed.
Datetime/time zones must be absent or exact fixed-offset `datetime.timezone` or Pydantic
`TzInfo` values; application-defined timezone callbacks are not invoked.
Unsupported values (including subclasses and non-finite floats), cycles, and nesting
beyond 64 containers become `"<unavailable>"`; non-string keys are omitted without conversion. It calls no
application serializers, copy, string, representation, or container hooks. The runtime
prompt receives its own detached projection, while bound operations retain the exact
validated Python values. This does not change the HTTP adapter's earlier body serialization
or path-parameter rendering.
Raw runtime inputs still undergo validation; ordinary request wrappers are not trusted.
Raw `Runtime.call` mappings use the same declared input contract for required fields,
defaults, aliases, and canonical typed values, whether the endpoint declares a Pydantic
request model or individual parameters. HTTP validation remains a one-shot handoff: runtime
preparation does not rerun request validators. Raw preparation does not call field serializers
or application copy/string hooks when it builds the model-facing prompt projection.
For a custom-initialized request contract, a raw mapping containing a model instance is
rejected before its constructor runs; provide the equivalent nested mapping so Pydantic can
validate it once. Already validated HTTP transport graphs remain one-shot handoffs.
Parameterless endpoints accept only an empty raw mapping; undeclared raw keys are rejected
before model execution or application value hooks can run. Their HTTP routes still expose no
request fields.


Supported immutable callable defaults are exact built-in `None`, `bool`, `int`,
`float`, `complex`, `str`, and `bytes` values, plus tuples and frozensets containing
only those values recursively. Custom types (including subclasses of those built-ins)
and mutable defaults keep the endpoint agent-backed; copy hooks are not proof of
immutability. Scalar request declarations also remain agent-backed.


## Authenticated application context (included from version 0.13.0)

Included from version 0.13.0, authenticated application context supports `FromContext` only on a single required operation with `calls=Exactly(1)`, and an admitted uniquely ordered required `Exactly(1)` chain. This was not part of version 0.12.0. It is application-authenticated context, not built-in login or authorization.

```python
import os
import secrets
from pydantic import BaseModel, ConfigDict
from summonpot import Exactly, FromContext, FromRequest, Operation, Required, Summon
from my_service.models import TenantRequest, TenantResponse
from my_service.operations import fetch_tenant


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: str


# In a real deployment, load a securely provisioned expected token and map
# verified credentials to the principal in your application's auth layer.
def authenticate(request) -> Principal:
    supplied = request.headers.get("authorization", "")
    expected = os.environ["SERVICE_TOKEN"]
    if not secrets.compare_digest(supplied, f"Bearer {expected}"):
        raise PermissionError
    return Principal(tenant_id=os.environ["SERVICE_TENANT"])


load_tenant = Operation(
    fetch_tenant,
    bind={"tenant_id": FromContext("tenant_id"), "record_id": FromRequest("record_id")},
    output=TenantResponse,
)
summon = Summon("service", context=authenticate)


@summon("/tenant")
def read_tenant(
    request: TenantRequest, result=Required(load_tenant, calls=Exactly(1))
) -> TenantResponse:
    """Read the authenticated tenant."""
    ...
```

The request object is only the HTTP-framework boundary for credential extraction. A real authenticator must verify credentials and return the server-derived identity; never create a success receipt, trust a body/header value without verification, or accept model-selected identity. The provider runs once per HTTP request inside the runtime timeout, before operations/model resolution. Its frozen Pydantic result must use `extra="forbid"` and immutable primitive/typed tuple/frozenset fields. Context field names are canonical model names (not aliases), and context values are not implicitly added to model inputs. Authentication denial maps to fixed 401; unexpected provider or invalid-context failures map to fixed redacted 500. Raw `Runtime.call(..., context=principal)` is trusted application code only, never HTTP/JSON authority. The app remains responsible for login, operation authorization, and tenant isolation.
The framework does not insert the context object or its values into model instructions, request prompts, schemas, or error responses. This is not a guarantee that a value is secret if application code discloses it: operation outputs may intentionally be returned to the model on the existing single-operation agent path, and that disclosure remains the application's responsibility. FastAPI transport validation occurs before the provider; provider execution is within `Runtime.timeout`. `PermissionError` maps to 401 only when raised by the context provider; an operation's `PermissionError` is an application failure (500).

Admission inspects canonical principal values without copying or coercion. Principal
validation hooks, custom initialization/post-init hooks, and transforming model config
are rejected at registration; perform normalization in the authenticator instead.

The snippet imports the real application's request/response models and operation; its
`TenantRequest` must declare `record_id`. The full runnable implementation is
`examples/13_authenticated_context/app.py`. The provider protects every declared Summon
endpoint, even without a context binding; documentation and OpenAPI routes remain outside
this authentication hook. Context receiving constraints for the whole
chain are preflighted before any operation. Existing direct eligibility still requires a
Pydantic request and at least one `FromRequest` binding; context-only declarations remain
agent-mediated. Authenticated HTTP uses standard `Runtime.call`; overriding that method is
unsupported and fails closed. Context-unused custom runtimes retain their existing API.


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

Python 3.11 through 3.14 is supported.

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

One monotonic deadline covers runtime request preparation, execution, and final output validation. HTTP body parsing and request validation occur before the route handler and are outside this runtime deadline. Synchronous preparation/finalization cannot be forcibly preempted; after each returns, the runtime checks the same deadline before starting effects or returning output. Async cancellation is cooperative, and synchronous capabilities running in worker threads can continue after timeout. A timeout therefore means the outcome may be unknown, not that no effect happened. Use application-level deadlines/idempotency for irreversible work; the runtime does not retry or switch to a model after an effect starts.

## Failure responses

| Status | Meaning |
|---|---|
| `422` | request validation failed, or a validated request value failed a receiving operation contract |
| `429` | the endpoint exceeded its configured usage limit, or the provider rate-limited it |
| `502` | the model failed to satisfy its contract, the provider failed, or operation output failed validation |
| `504` | the endpoint exceeded its timeout |
| `500` | provider misconfiguration or application capability failure |

Bodies use fixed messages. Normal logs include only allowlisted endpoint and failure categories; exception text and chains, provider bodies, validation inputs, prompts, outputs, and capability data are omitted. HTTP request-validation errors are redacted too. These mappings do not imply redesigned deadline or result-chain semantics.

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
  callable capabilities still receive model-supplied arguments. A fully resolved
  exact-response operation runs directly, and an admitted operation with direct
  `AgentChoice` uses the agent path. Unsupported explicit operation shapes are rejected at
  registration. Validate inputs and enforce authorization inside every capability.
