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
- The docstring is the fixed endpoint goal.
- Dependencies are the complete set of deterministic operations exposed to the agent.
- The Pydantic return model is the required output contract.

## Dependency semantics

`Depends(operation)` exposes an exact operation that the agent may call.

`Required(operation)` exposes an exact operation and prevents successful final output until that operation has completed.

Required use is checked by runtime state. It is not only written into the prompt.

## Typed operation dataflow

`Operation` adds a validated declaration of where capability arguments are intended to
come from without adding configuration to `@summon(...)`:

```python
from summonpot import AgentChoice, FromRequest, FromResult, Operation


customer = Operation(
    load_customer,
    bind={"customer_id": FromRequest("customer_id")},
    output=CustomerRecord,
)
ticket = Operation(
    create_ticket,
    bind={
        "customer_id": FromResult(customer, "customer_id"),
        "priority": AgentChoice(),
        "summary": AgentChoice(),
    },
    output=TicketReceipt,
    after=(customer,),
)
```

`FromRequest` names validated request data. `FromResult` names a field on a declared
producer's typed output. `FromContext` names framework-owned state. `AgentChoice` is the
explicit model-controlled source. Registration rejects incomplete bindings, missing
fields, undeclared producers, and types known to be incompatible. Dependency cycles are
structurally unrepresentable through the immutable public `Operation` API rather than
discovered by a separate cycle detector.

The declarations are immutable and shipped today. The first runtime-enforced slice covers
an endpoint with one required `Exactly(1)` operation whose arguments use `FromRequest`,
direct `AgentChoice`, or callable defaults. Trusted/defaulted arguments are absent from the
model schema, the single start is reserved before application code, and `output=` is
validated before the operation satisfies `Required`.

Multi-operation chains, `FromResult`, `FromContext`, `after`, and broader call bounds remain
registration-only. See [`08_direct_execution.py`](../examples/08_direct_execution.py) for the
credential-free direct slice, [`07_bound_operation.py`](../examples/07_bound_operation.py)
for the agent-backed enforced slice, and
[`06_support_service`](../examples/06_support_service/app.py) for the broader declared chain.

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
Any unresolved choice or unsupported declaration remains on the provider-neutral agent loop.

Dependency parameters are declaration-only. They do not appear in the HTTP request body
or OpenAPI request schema. The ellipsis is the complete declaration body, and direct calls
to a registered declaration are rejected; execution goes through the generated endpoint.


Supported immutable callable defaults are exact built-in `None`, `bool`, `int`,
`float`, `complex`, `str`, and `bytes` values, plus tuples and frozensets containing
only those values recursively. Custom types (including subclasses of those built-ins)
and mutable defaults keep the endpoint agent-backed; copy hooks are not proof of
immutability. Scalar request declarations also remain agent-backed.

## What the boundary does and does not cover

Output from runtime-enforced operations is validated against its declared schema without
invoking serializers.
When an existing model instance allows extras, a colliding extra cannot overwrite a
canonical field. During this revalidation, model `before` validators receive canonical
fields plus noncolliding extras; colliding extras are validated separately and restored
before model `after` and outer `wrap` validators observe the result. Caller-owned model
storage is not rewritten. Raw mapping outputs retain their declared alias policy.

The endpoint agent receives its declared dependencies and no ambient application access. An operation can contain deterministic business logic or a safe database adapter. Raw database sessions, connections, cursors, ORM registries, shells, and arbitrary SQL execution should not be exposed.

For databases, the target adapter API accepts exact prepared operations rather than broad infrastructure objects:

- a developer-declared SQLAlchemy `Select`, `Insert`, `Update`, or `Delete` statement;
- a fixed parameterized SQLite statement specification;
- explicit bind sources such as validated request fields;
- a typed projection or write receipt;
- a framework-owned session or connection factory that is never agent-visible.

The agent receives the operation's typed callable schema—not the statement, SQL text, ORM metadata, session, engine, connection, or cursor. It cannot edit the query or execute another one.

### Arguments are constrained for the first bound runtime slice

The closed set always covers *which* operations the agent may call. For one required
`Exactly(1)` operation using `FromRequest`, direct `AgentChoice`, or callable defaults, the
runtime now also constrains *what the model may pass*:

- `FromRequest` receives the canonical validated request value and is absent from the model schema;
- callable defaults are absent from the model schema and remain application-owned;
- only direct `AgentChoice` arguments are model-supplied;
- a second start is rejected before application code; and
- invalid `output=` data does not satisfy `Required` and is not retried automatically.

Broader operation shapes retain their existing model-supplied argument behavior until the
complete graph semantics ship. In particular, `FromResult`, `FromContext`, `after`, and
collection-backed choices are still declarations rather than runtime injection. Continue
to validate inputs and enforce authorization inside every operation; trusted binding does
not grant authorization or prove that final model claims match operation results.

Extending these guarantees across operation graphs is milestone 1 on the
[roadmap](../ROADMAP.md).

Strict SQLAlchemy and SQLite operation objects are planned and not yet shipped. See the target API examples in the README and the implementation sequence in the roadmap.
