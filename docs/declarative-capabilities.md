# Declarative capability endpoints

Current source (unreleased) permits `Operation(fn, bind=...)` to omit `output=` when the callable has a resolved, non-empty return annotation. Registration snapshots the full annotation, including `Annotated` metadata, without mutating the original declaration. Explicit outputs remain authoritative; input bindings are never inferred. Published v0.14.0 requires explicit outputs.


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

## Current source: repeated stage with final-result consumer (unreleased)

This describes the original two-operation form. The single-stage chain section below extends its composition without changing final-invocation addressing.

The current source admits a narrow two-operation sequence: one required repeated producer,
then one required `Exactly(1)` terminal consumer. The producer uses positive finite bounds
(`minimum >= 1`, `maximum > 1`), a Pydantic request with at least one `FromRequest`, direct
plain-string `Literal` choices, and supported request/context bindings or immutable defaults.
Its validated Pydantic output is an intermediate type, distinct from the endpoint response.
The terminal operation has no choices, consumes at least one explicit
`FromResult(producer, field, invocation="final")`, and returns the exact full endpoint
response annotation. Its other inputs use supported request/context/default sources.

`invocation="final"` addresses the final successful invocation of a closed repeated stage.
Unqualified `FromResult(producer, field)` retains its single-invocation meaning and is rejected
for repeated producers; selectors other than `"final"` are unsupported. All final fields
come from one immutable closure record containing producer identity, invocation ordinal and
canonical validated result. The stage closes only after the effective minimum succeeds, no
invocation is running, and the selected final invocation succeeded. The model may legally
finish or maximum completion closes automatically without another acknowledgment. Terminal
readiness does not follow from meeting the minimum alone. Failure, cancellation or uncertain
outcome after any earlier success aborts; no earlier-result fallback is allowed.

This is a current-source, unreleased shape; published v0.14.0 is unchanged. It does not add
aggregated repeated results, arbitrary invocation selectors, repeated consumers, producer
choices from repeated results, optional/unbounded/multiple repeated stages, general graphs,
cycles, parallelism, or durable resume. The inspect/correct/verify workflow is not thereby
implemented. See the focused [repeated-stage result contract](repeated-stage-results.added.md).

## Current source: one repeated stage in a sequential chain (unreleased)

Current source (unreleased) supports a uniquely ordered chain with one nonterminal bounded repeated operation, an optional resolved prefix and a nonempty resolved suffix. Every other operation is required `Exactly(1)` with no agent choices. A Pydantic request needs at least one `FromRequest` across the whole chain, not necessarily on the repeated operation; supported request/result/authenticated-context bindings and immutable defaults remain required. The repeated operation has positive finite bounds (`minimum >= 1`, `maximum > 1`), direct closed plain-string `Literal` choices and a Pydantic intermediate distinct from the response. Ordinary `FromResult` reads single-invocation results; repeated results require `invocation="final"`, with at least one suffix consumer. Exactly one terminal operation owns the endpoint's exact full response annotation. Prefix operations run before one lazy model resolution; suffix operations run after immutable stage closure without further model decisions or acknowledgment. One principal, ledger, absolute deadline and usage budget span the request. Prefix results/context/ledger are not implicitly projected into model prompts; receiving constraints are checked before each start. Explicit function-tool quotas reject before all work. No feedback cycles, external choices, multiple repeated stages, aggregation, parallelism or durable recovery are added. Published v0.14.0 is unchanged.

The original two-operation shape above remains its zero-prefix, one-consumer case. Meeting the minimum alone never readies downstream work: both final-result bindings and `after` dependencies require the same immutable closure. Prefix effects can precede missing-provider failure; suffix failures can follow committed work without rollback or replay. See the [complete admission and failure contract](stage-chains.added.md).

## Current source: one prefix selection before repetition (unreleased)

Current source (unreleased) also composes exactly one producer-backed choice argument on one required `Exactly(1)` prefix consumer with one nonterminal bounded repeated stage and a resolved suffix. The candidate producer is an earlier single-start operation returning `list[ConcreteModel]`; repeated choices remain direct closed string `Literal` values, and all other operations remain resolved required `Exactly(1)`. Pydantic request/response, chain-wide `FromRequest`, unique ordering, final-invocation addressing and exact terminal response ownership remain required. Empty/unavailable/oversized candidate domains stop before selection or repeated work; a singleton binds locally, while ambiguity uses canonical request-local tokens. Singleton selection still leads to model-backed repeated decisions. One lazy model-configuration lookup, run, principal, ledger, deadline and usage budget span both phases. No business-function tools, reselection after same-run failure, effect replay or final model acknowledgment are added. A fresh request starts a fresh run. Published v0.14.0 is unchanged. See [the complete composed contract](choice-before-stage.added.md).


## Current-source bounded checkpoint progression (unreleased)

Current source supports one explicit `Required(check, calls=Between(1, M), until="accepted")` marker, with finite `M >= 2`. The marker must name a stored, non-null strict Boolean field in the checkpoint's validated Pydantic output; aliases, computed properties, expressions and coercive Boolean fields do not qualify. `until=None` keeps ordinary `Required` behavior. A uniquely ordered required region ends at the checkpoint, with effective bounds `1..M`; a nonempty uniquely ordered optional negative continuation has bounds `0..M-1`. Exactly one `Required(..., calls=Exactly(1))` terminal returns the endpoint's exact full response annotation and reads only fields from the final checkpoint invocation. Invalid marked shapes fail registration, never fall back to the legacy route.

True closes to terminal. False runs the declared continuation, then rechecks; the Mth false closes unresolved to terminal without another continuation. The application owns the truth of the check, candidate permissions and truthful report. An empty choice domain fails closed with the existing redacted 409; it is not an unresolved report. Only one frame operation is in flight. Continuation admission retires that round’s authority atomically, so closure cannot race it; only a fresh checkpoint after continuation can close. Every invocation uses the existing shared kernel. The shared request, authenticated principal, invocation ledger, usage budget and absolute deadline span all rounds. There is no rollback, effect replay, durable resume or recovery: a prior write/report may remain after later failure, and a fresh request is not safe recovery. Published v0.14.0 does not include checkpoint progression. See [examples 18 and 19](../examples/README.md#18-bounded-checkpoint-cleanup-current-source-unreleased) and the [complete contract](checkpoint-progression.added.md).

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

Broader explicit operation shapes are rejected before serving until their execution
semantics ship. Published chain behavior requires exactly one ready operation at each
step. Current source additionally supports `FromResult` and `after` in the fully resolved
branch/join slice above, with stable sequential readiness and one exact terminal response.
Producer-backed `AgentChoice(from_result=...)` remains restricted to uniquely ordered
chains and producer outputs `list[ConcreteModel]`, under the bounded tokenized contract
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


## Current-source branch/join execution (unreleased)

Current source supports a narrow fully resolved branch/join graph without widening the public API. The endpoint must have a Pydantic request and response, at least one `FromRequest` binding, and required `Exactly(1)` operations forming an acyclic graph. Inputs may be supported request bindings, validated `FromResult` values, authenticated `FromContext` values, or supported immutable callable defaults. Every operation must reach the unique sink, and exactly one operation must declare the endpoint's exact full response annotation. `AgentChoice` is not admitted.

Readiness is inferred from result dependencies and `after` ordering. Execution remains sequential; when multiple operations are ready, declaration order is the stable tie-break. `after` imposes business ordering but does not authorize disconnected vertices, multiple sinks, cycles, choices, or unsupported inputs. Existing chain/choice/repetition/checkpoint routes are unchanged. This is not a public graph API or parallel scheduler. Published v0.14.0 is unchanged; milestone 4 is partial and milestone 3 remains partial. See [example 20](../examples/20_branch_join/README.md).
