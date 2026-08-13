# Declarative capability endpoints

A summonpot endpoint is a declaration, not a Python handler.

```python
@pot.summon("/research")
def research(
    request: ResearchRequest,
    sources=Required(load_sources),
    ranking=Depends(rank_sources),
) -> ResearchResponse:
    """Research using only the declared operations."""
    raise NotImplementedError
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

## Deterministic and agentic execution

Capabilities are deterministic operations in both modes. The difference is whether execution still has an unresolved legal choice:

```text
one complete path → deterministic execution
bounded choice remains → agentic execution
no legal path → typed deterministic error
```

The public endpoint declaration stays the same. The fixed docstring goal and validated request determine the work; callers do not send an `action` field or select an agent framework. Automatic deterministic endpoint execution is planned—the current runtime still executes `@pot.summon` requests through the provider-neutral agent loop.

Dependency parameters are declaration-only. They do not appear in the HTTP request body or OpenAPI request schema, and the decorated function body is never executed.

## Closed boundary

The endpoint agent receives its declared dependencies and no ambient application access. An operation can contain deterministic business logic or a safe database adapter. Raw database sessions, connections, cursors, ORM registries, shells, and arbitrary SQL execution should not be exposed.

Strict SQLAlchemy and SQLite operation objects will build on this capability contract in a separate change.
