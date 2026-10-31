# Declarative capability endpoints

A summonpot endpoint is a declaration, not a Python handler.

The opening fragment focuses on the declaration shape and assumes the application-specific
request models and operations are defined elsewhere. For a standalone runnable application,
start with the [quick start](../README.md#quick-start).

```python
from summonpot import Depends, Required, Summon


summon = Summon("research-api")


@summon("/research")
def research(
    request: ResearchRequest,
    sources=Required(load_sources),
    ranking=Depends(rank_sources),
) -> ResearchResponse:
    """Research using only the declared operations."""
    ...
```

The signature defines four things:

- The Pydantic request model is the JSON contract.
- The docstring is the fixed execution goal.
- Dependencies are the complete set of deterministic operations available to execution.
- The Pydantic return model is the required output contract.

`Annotated[RequestModel, ...]` and `Annotated[ResponseModel, ...]` retain their
validation and schema metadata across runtime execution and HTTP. Application response
validators run during runtime validation, not again during HTTP serialization. The
transport retains the registered schema, serializers, and inert output-storage audit.
The request remains a flat model body, not a nested parameter wrapper. Endpoint inspection
exposes the
underlying model classes and the full annotations separately. For direct execution,
the operation output must be the exact response annotation, including its metadata;
a bare model output does not satisfy an annotated response contract.

Scalar business parameters named `self` or `cls` are ordinary request fields, not
implicit receivers. Actual unbound endpoint methods are rejected; declare an endpoint
as a standalone function or pass an already-bound callable.

## Dependency semantics

`Depends(operation)` makes an exact operation available to execution. On the agent-backed
path, the agent may call it.

`Required(operation)` makes an exact operation available and prevents successful final
output until that operation has completed.

Required use is checked by runtime state. It is not only written into the prompt.

## Typed operation dataflow

`Operation` adds an enforceable declaration of where capability arguments come from without
adding configuration to `@summon(...)`:

```python
from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required


customer = Operation(
    load_customer,
    bind={
        "customer_id": FromRequest("customer_id"),
        "format": AgentChoice(),
    },
    output=CustomerRecord,
)


@summon("/customers")
def get_customer(
    request: CustomerRequest,
    customer_result=Required(customer, calls=Exactly(1)),
) -> CustomerResponse:
    """Load this customer and return the approved view."""
    ...
```

`FromRequest` names validated request data and direct `AgentChoice` is the explicit
model-controlled source. Registration rejects incomplete bindings, missing fields, and
types known to be incompatible. Binding objects must be exact built-in source vocabulary
types; subclasses are rejected.

The declarations are immutable and shipped today. The first runtime-enforced slice covers
an endpoint with one required `Exactly(1)` operation whose arguments use `FromRequest`,
direct `AgentChoice`, or callable defaults. Trusted/defaulted arguments are absent from the
model schema, the single start is reserved before application code, and `output=` is
validated before the operation satisfies `Required`.

Version 0.11.0 also admits a sequential chain of required `Exactly(1)` operations
with exactly one ready operation at each step, without a two-operation ceiling,
connected by `FromResult` or `after`. Bound result fields are read only after local producer
validation, and the response is the canonical result of the unique terminal operation whose
full output annotation exactly matches the endpoint. Version 0.11.0 chains are agent-mediated;
canonical results stay outside model context. Within a chain, `AgentChoice(from_result=producer)`
selects from a producer's validated `list[ConcreteModel]`, projecting inert descriptions and
opaque request-local tokens rather than canonical objects or full result context. The chosen
token maps to that exact canonical member; Python equality is not authority. Projection
respects field exclusions and aliases without application serializers. Limits are 128
candidates and 65,536 JSON characters per binding. Empty, unavailable, or oversized sets
fail with a fixed redacted 409 before model decision and downstream work, with no extra model
request. Primitive/untyped collections, direct unbounded chain choices, context bindings
outside the authenticated source slice below, and broader graphs and bounds remain
unsupported and rejected at registration. A multi-candidate
choice remains agent-mediated, not model-free; direct single-operation `AgentChoice` is
unchanged. See
[`10_result_chain`](../examples/10_result_chain/README.md) for the persisted inventory example and
[`08_direct_execution.py`](../examples/08_direct_execution.py) for the
credential-free direct slice, [`07_bound_operation.py`](../examples/07_bound_operation.py)
for the agent-backed enforced slice, and [`06_support_service`](../examples/06_support_service/app.py)
for a multi-file service using compatible bare callable dependencies.

## Current source: framework-owned decision progression (unreleased)

This is the current source extension, not behavior in published v0.14.0. The released
v0.14.0 optimization remains exactly one producer-backed choice argument across an
otherwise eligible chain, with no other choice. The current source supports one or more
producer-backed choices in an otherwise eligible uniquely ordered chain of at least two
required `Exactly(1)` operations. It still requires a Pydantic request with at least one
`FromRequest`, supported request/result/authenticated-context bindings or immutable
defaults, and the exact full terminal operation/endpoint response annotation. The choice
producers must be supported `list[ConcreteModel]` operations preceding their consumers.

Summonpot advances execution between decision boundaries. It checks **every** producer-backed
domain for the next consumer before selecting or starting that consumer. Empty, unavailable,
or oversized domains fail with the existing redacted conflict; singleton domains bind their
canonical member locally. Only ambiguous binding slots reach a private decision selector,
which sees the fixed goal, safe projected request data and bounded inert per-slot evidence.
It has no business-function tools, database access, ledger, implicit principal or authority
to finish the endpoint. The strict selector returns opaque tokens only; local membership,
receiving constraints, readiness and reservation checks precede the operation start in the
shared invocation kernel. Multiple ambiguous arguments at one consumer are selected together.
Progression repeats locally at subsequent frontiers, and the unique terminal operation's
canonical validated result is returned immediately without a model-authored completion.

The request, authenticated context, exact results, reservations, token domains, effective
usage limits and absolute deadline remain request-local and shared across every frontier and
correction. The configured model resolves lazily once at the first ambiguity. Corrections
consume the shared request/token/cost budgets and deadline; they cannot replay an effect,
reset the deadline or renew candidate authority. The per-binding caps remain 128 candidates and
65,536 evidence characters; these are not aggregate prompt/context or Cartesian-product
limits. Projection is bounded and inert; it does not imply secrecy for caller request data or
application outputs intentionally disclosed by operations.

This unreleased route is unavailable when an explicit `tool_calls_limit` is configured,
because decision-only structured output reports no business function calls; that setting
retains the supported legacy agent suffix. `allow_direct=False` likewise preserves the
existing compatibility route. Declarations outside optimization eligibility retain their
previous supported behavior. Prefix effects may precede lazy provider-configuration failure;
there is no rollback, effect replay, durable cross-request resume, repeated-call support,
general graph compiler or public selector. Historical release sections are unchanged.

## Current source: bounded repeated calls (unreleased)

The minimum is the effective bound after existing marker normalization: `Required(op, calls=AtMost(3))` still requires at least one validated success. Optional/zero-success execution is not admitted.

The repeated-call slice admits one explicitly required, typed operation with finite positive
bounds `1 <= minimum <= maximum` and `maximum > 1`, a Pydantic request with at least one
`FromRequest`, and at least one direct `AgentChoice` bound to closed `Literal[str]` choices.
Remaining inputs use supported request/context bindings or immutable defaults, and the
operation's full output annotation exactly matches the endpoint response annotation. No
producer choice, `FromResult`, ordering, second capability, zero minimum, unbounded call,
implicit batch, or general graph is included. Existing exactly-once and producer-choice
routes retain their current behavior. See the [bounded repeated-calls contract](bounded-repeated-calls.added.md).

Summonpot owns sequential invocation and enforces legal finish decisions; business functions are not
provider tools. Selector arguments are locally validated. Starts are bounded atomically,
minimum counts validated successes, and reaching the maximum finalizes automatically without
a model acknowledgment. The response is the canonical result of the final successful
invocation only; any invocation failure aborts, with no earlier-success fallback or aggregate
collector. One shared usage budget and deadline span decisions; model resolution is lazy.
The new shape rejects explicit `tool_calls_limit` before provider resolution or application
effects, with no repeated-call fallback. Previous-result evidence is capped at 65,536
characters per decision; bounded caller request data and declared evidence may be disclosed
to the selector, but no principal or full result ledger is implicitly exposed.

## Deterministic and agentic execution

Capabilities are deterministic operations in both modes. The difference is whether execution still has an unresolved legal choice:

```text
one complete path → deterministic execution
bounded choice remains → agentic execution
no legal path → typed deterministic error
```

The public endpoint declaration stays the same. The fixed docstring goal and validated
request determine the work; callers do not send an `action` field or select an agent
framework. When the endpoint uses a Pydantic request model and registration proves there
is exactly one required `Exactly(1)` operation,
at least one argument is bound from `FromRequest`, every remaining argument comes from
`FromRequest` or an immutable identity-stable callable default, and its declared output is
the endpoint output model by exact identity, the runtime executes that operation directly
before model resolution. There is no model fallback after direct execution starts.
From 0.12.0, fully resolved chains run model-free only with a Pydantic request and at least one `FromRequest`, uniquely ordered required `Exactly(1)` steps, supported request/result/authenticated-context sources and immutable defaults, and an exact full terminal response annotation. Any `AgentChoice` in a published v0.13.0 chain remains agent-mediated. Included from version 0.14.0, a narrow result-dependent path is shipped for exactly one producer-backed choice argument across the entire otherwise eligible chain, with no other choice. A singleton binds locally; multiple candidates cause lazy model handoff after the prefix. Current source (unreleased) supports one or more producer-backed choices with framework-owned progression. In an otherwise eligible uniquely ordered required `Exactly(1)` chain, a Pydantic request, at least one `FromRequest`, supported request/result/authenticated-context bindings or immutable defaults, and exact full terminal response annotation identity remain required. All current consumer domains are checked before selection or start. Singleton bindings resolve locally; a decision-only selector returns ambiguous tokens with no business-operation tools. The shared kernel validates and invokes the operation, then continues locally until another genuine decision is needed. The canonical terminal result returns without a final model acknowledgment. Request/principal, reservations, token domains, usage budgets and one deadline remain request-local across frontiers and corrections. Explicit `tool_calls_limit` retains the previous one-way agent suffix; `allow_direct=False` and other noneligible declarations retain their existing route. Limits remain 128 candidates and 65,536 evidence characters per binding, not an aggregate prompt/context budget. Prefix effects may precede provider-configuration failure; no rollback, effect replay or durable resume is added. Historical v0.14.0 remains exactly-one-choice. See the [operation reference](https://summonpot.modepot.io/reference/operations/) for details.
A direct `AgentChoice` in the admitted shape uses the provider-neutral agent loop. An
unsupported explicit declaration fails before serving; bare callable dependencies keep their
legacy agent behavior. `Operation(fn)` is still an explicit contract and is rejected because
it does not provide the complete enforced shape.

Dependency parameters are declaration-only. They do not appear in the HTTP request body
or OpenAPI request schema. The ellipsis is the complete declaration body, and direct calls
to a registered declaration are rejected; execution goes through the generated endpoint.


Supported immutable callable defaults are exact built-in `None`, `bool`, `int`,
`float`, `complex`, `str`, and `bytes` values, plus tuples and frozensets containing
only those values recursively. Custom types (including subclasses of those built-ins)
and mutable defaults keep the endpoint agent-backed; copy hooks are not proof of
immutability. Scalar request declarations also remain agent-backed.

## What the boundary does and does not cover

HTTP validation hands the framework-owned validated value graph to the runtime exactly
once. The transport carrier exposes separate compatibility views for custom runtimes;
mutating those views cannot change operation inputs, and replaying a consumed transport
carrier is rejected. The framework does not call application-defined copy hooks while
handing values off.
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
As with any Pydantic application validator, code that retains and later mutates an object
it returned remains application-owned behavior rather than a second request input.
Raw `Runtime.call` mappings use the endpoint's declared request contract once, matching HTTP
required fields, defaults, aliases, and canonical typed values for Pydantic request models
and individual parameters. Unlike the body adapter's model-facing rendering, raw runtime
preparation does not call declared field serializers, application copy hooks, or string hooks.
Custom-initialized request contracts reject raw mappings containing model instances before
the custom constructor runs; pass the equivalent nested mapping instead. This explicit
boundary prevents constructed instances from bypassing nested validation or authorizing an
unchecked original after a coercing validation pass. Already validated HTTP transport graphs
remain one-shot handoffs and are not revalidated.
For a parameterless endpoint the raw contract is explicitly empty: undeclared keys are rejected
before model execution or application value hooks, while HTTP exposes no request fields.

Output from runtime-enforced operations is validated against its declared schema without
invoking serializers. Custom model `__init__` methods in these output schemas (including
nested models) are rejected at registration: core's custom-constructor path can leave the
compiled validator and trust unchecked nested instances. Use Pydantic model validators
rather than a custom initializer for supported output validation.
Validation and serialization namespaces are checked separately. Enabled direct validation
aliases cannot claim the same input key under the model's configured validation policy, while
declared fields, serialization aliases, and computed
fields must produce distinct emitted JSON object keys. This structural admission runs at
registration for every endpoint response model and every declared operation `output=` shape,
including nested models, dataclasses, typed dictionaries, multi-operation declarations, and
operation shapes outside the currently enforced runtime slice. It does not claim runtime
structural validation for those broader operation graphs; their execution remains unsupported.
For runtime-enforced models with `extra="allow"`, both existing instances and raw mappings are
rejected after model construction if an extra shadows either a canonical field name or an
emitted alias. Noncolliding extras remain supported and typed extras are still validated.
These checks do not serialize, copy, stringify, or take the representation of application
values, and caller-owned model storage is not rewritten. Raw mappings retain their declared
validation-alias policy.

The endpoint agent receives its declared dependencies and no ambient application access. An operation can contain deterministic business logic or a safe database adapter. Raw database sessions, connections, cursors, ORM registries, shells, and arbitrary SQL execution should not be exposed.

For databases, the target adapter API accepts exact prepared operations rather than broad infrastructure objects:

- a developer-declared SQLAlchemy `Select`, `Insert`, `Update`, or `Delete` statement;
- a fixed parameterized SQLite statement specification;
- explicit bind sources such as validated request fields;
- a typed projection or write receipt;
- a framework-owned session or connection factory that is never agent-visible.

The agent receives the operation's typed callable schema—not the statement, SQL text, ORM metadata, session, engine, connection, or cursor. It cannot edit the query or execute another one.

### Arguments are constrained for the first bound runtime slice

The closed set always covers *which* operations execution may use. On the agent-backed path,
the agent may call only that set. For one required `Exactly(1)` operation using
`FromRequest`, direct `AgentChoice`, or callable defaults, the runtime now also constrains
*what the model may pass*:

- `FromRequest` receives the canonical validated request value and is absent from the model schema;
- callable defaults are absent from the model schema and remain application-owned;
- only direct `AgentChoice` arguments are model-supplied;
- a second start is rejected before application code; and
- invalid `output=` data does not satisfy `Required` and is not retried automatically.

On both the direct and agent-backed forms of this supported slice, every injected
`FromRequest` value is checked against its receiving operation parameter, including
`Annotated` primitive constraints, strictly before application code starts. The check is
noncoercive: a broader request contract cannot satisfy a narrower receiver by conversion.
When the check succeeds, the canonical validated request value is passed unchanged, not
replaced by a coerced value, and request-model validators are not rerun.

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

Broader explicit operation shapes are rejected before serving until complete graph semantics
ship. `FromResult` and `after` are supported only in a sequential chain where each step has
exactly one ready operation. Producer-backed `AgentChoice(from_result=...)` is supported
there only for producer outputs `list[ConcreteModel]`, under the bounded tokenized contract
described above. Authenticated `FromContext` outside its narrow supported source slice, primitive/untyped collections, broader bounds, and unsupported graph shapes cannot fall through to unenforced model
arguments. Bare callable dependencies retain the legacy agent path. Continue to validate
inputs and enforce authorization inside every operation; trusted binding does not grant
authorization or prove that final model claims match operation results.

Extending these guarantees across operation graphs begins in milestone 2 on the
[roadmap](../ROADMAP.md).

Strict SQLAlchemy and SQLite operation objects are planned and not yet shipped. See the target API examples in the README and the implementation sequence in the roadmap.


### Authenticated application context (included from version 0.13.0)

Included from version 0.13.0, the source admits `FromContext` only for a single required operation with `Exactly(1)` and an eligible uniquely ordered required `Exactly(1)` chain. This was not included in version 0.12.0. Register `Summon(context=authenticate)` with a sync or async one-request-argument function returning a Pydantic principal configured `frozen=True, extra="forbid"`. Fields must be immutable primitive values or typed tuples/frozensets. `FromContext("tenant_id")` refers to the canonical field name, not its validation alias.

The provider executes anew for each HTTP request inside `Runtime.timeout`, before operations and model resolution. Authentication denial yields a fixed 401; unexpected provider/invalid principal failures yield fixed redacted 500 responses. Context values are not implicitly added to model inputs. Request JSON is not authority. Raw `Runtime.call(..., context=principal)` is a trusted application entry point only. This feature does not implement login, credential policy, operation authorization, or tenant-scoped data access; the application must perform all of those.
The framework does not insert the context object or its values into model instructions, request prompts, schemas, or error responses. This is not a guarantee that a value is secret if application code discloses it: operation outputs may intentionally be returned to the model on the existing single-operation agent path, and that disclosure remains the application's responsibility. FastAPI transport validation occurs before the provider; provider execution is within `Runtime.timeout`. `PermissionError` maps to 401 only when raised by the context provider; an operation's `PermissionError` is an application failure (500).

Principal admission is a non-transforming structural predicate over the authenticator's
canonical values. Validation hooks, custom initialization/post-init hooks, and transforming
model configurations fail registration rather than being replayed to change identity.
