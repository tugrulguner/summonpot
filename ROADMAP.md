# summonpot roadmap

summonpot is modernizing APIs for AI around one endpoint contract:

```text
Pydantic request model
+ fixed endpoint goal
+ exact application-owned operations
+ explicit agent-owned choices when needed
+ Pydantic response model
= executable endpoint
```

The endpoint body is declarative and is never the handler. Request JSON carries business
data, not an action selector. The same simple contract supports direct deterministic
execution for the narrow complete path shipped below; all other requests use the agent
runtime. For the enforced single required `Exactly(1)` slice, Summonpot hides and injects
application-owned arguments and leaves only declared `AgentChoice` values to the agent.
Unsupported shapes retain legacy model-supplied argument behavior until their full semantics
ship. The typed HTTP endpoint stays stable as that balance changes.

## Shipped foundation

The current release line provides:

- Pydantic request validation and OpenAPI request schemas.
- Pydantic response contracts with local final validation.
- Provider-neutral model selection and structured output.
- Optional deterministic operations through `Depends(operation)`.
- Runtime-enforced mandatory operations through `Required(operation)`.
- A closed endpoint capability set: undeclared operations are unavailable.
- Declarative dependency parameters that never become HTTP fields.
- Bounded retries when model output is invalid or required use is missing.
- Configurable request, token, cost, and timeout limits for each endpoint call.
- Redacted HTTP mappings for usage limits, timeouts, provider failures, and unsatisfied model contracts.
- GET, POST, PUT, PATCH, DELETE, and HEAD routing with validated body or query contracts.
- A keyless test model for exercising routing and capability wiring without provider credentials.
- Installable coding-agent skills describing the endpoint contract, typed operation bindings, and the current runtime boundary for Claude Code, Cursor, Windsurf, GitHub Copilot, Cline, and OpenAI Codex.
- Ellipsis declaration bodies that avoid abstract-method semantics, with direct Python calls rejected at the decorator boundary.
- Immutable `Operation` declarations with `FromRequest`, `FromResult`, `FromContext`, and `AgentChoice` argument sources.
- Runtime enforcement for one required `Exactly(1)` operation using `FromRequest`, direct `AgentChoice`, or callable defaults: trusted arguments are hidden and injected, the one start is reserved before invocation, and declared output is locally validated before success.
- Single-operation deterministic execution when that slice has no `AgentChoice`, contains at
  least one `FromRequest` binding, uses only `FromRequest` or immutable identity-stable
  callable defaults, and the operation output is exactly the endpoint response model:
  Summonpot executes directly without resolving or constructing a model.
- Declarative call bounds and ordering references without adding decorator configuration.
- Registration-time validation for complete bindings, request and result references, operation ordering, selectable collections, and provable type incompatibility.
- Python 3.11–3.13 CI, package builds, and expanded runtime/CLI coverage.

### 0.5.0 boundary

Version 0.5.0 ships the vocabulary and registration checks for typed operation dataflow.
It does not yet inject those bindings during execution. The current model runtime still
supplies capability arguments, and every reachable capability must validate and authorize
its inputs exactly as it did before 0.5.0.

### 0.6.0 boundary

Version 0.6.0 standardizes the public application API on `Summon`, a module-level
`summon`, and direct `@summon(...)` registration. It also makes ellipsis the complete
declaration body and rejects direct Python calls to registered declarations. The execution
boundary is unchanged from 0.5.0: typed bindings, ordering, and call bounds are validated
and stored, but the current runtime does not inject or enforce them yet.

### Current development boundary

The bound runtime enforces one required `Exactly(1)` operation whose inputs come from
`FromRequest`, direct `AgentChoice`, or callable defaults. It snapshots the validated
declaration at registration, hides trusted/defaulted arguments from the model, reserves the
only permitted start before application code, and validates the operation output before
recording success.

When that endpoint uses a Pydantic request model, has no `AgentChoice` or other unresolved
source, and the operation output is exactly the endpoint response model, the same invocation
kernel executes it directly without resolving or constructing a model. There is no model
fallback after direct execution begins. The endpoint remains agentic when `AgentChoice`,
final response composition, or any unsupported shape requires the model.

The completed single-operation deterministic execution milestone therefore applies to
exactly one required `Exactly(1)` operation with at least one `FromRequest` binding, only
`FromRequest` or immutable identity-stable callable defaults, and an operation output exactly
matching the endpoint response model. It runs without resolving, constructing, or calling a model. The broader
multi-operation deterministic compiler remains planned.

Multi-operation graphs, `FromResult`, `FromContext`, `after`, broader call bounds, and
broader no-model execution remain planned. Those unsupported shapes retain the 0.6.0
model-supplied argument behavior until their full semantics ship.

## Next milestones

The ordering below reflects the researched technical dependencies, not promised release
dates. Each slice keeps the public `@summon` declaration unchanged and adds no executor
selection flag, public graph, or handler body.

### 1. Validated result chains

Add the first private multi-operation execution semantics through a sequential required
`Exactly(1)` chain:

- Store validated results by operation identity for the lifetime of one request.
- Inject `FromResult` values only after their declared producer succeeds.
- Enforce `after` as a control dependency without treating it as a data binding.
- Compile cycle checks, stable dependency order, and readiness before exposing or invoking
  an operation.
- Validate every operation output before a later operation can consume it.
- Never replay the whole endpoint or fall back to a fresh model plan after an effectful
  operation starts.

Execution remains sequential initially. Parallel ready operations are deferred until
idempotency, transaction, or read-only semantics make concurrency safe.

### 2. Producer-constrained agent choices

Constrain `AgentChoice(from_result=...)` to the exact validated collection produced during
the same request:

- Expose only choices from a successful declared producer.
- Use stable internal membership tokens rather than trusting reconstructed model values or
  Python equality.
- Enforce membership locally; generated tool schemas provide guidance, not authority.
- Reject empty or unavailable choice sets deterministically instead of spending model
  retries on an impossible path.

### 3. Authenticated application context

Activate `FromContext` only after the framework has an authenticated, application-owned
context contract:

- Context values come from immutable request-local framework state, never prompt text or
  caller-controlled capability arguments.
- Context types and missing-value behavior are validated before operation invocation.
- Secrets remain hidden from model-visible signatures, schemas, descriptions, and errors.

### 4. Broader bounds and private path classification

Extend the identity-keyed invocation ledger and private plan after the exact-once slices are
stable:

- Enforce broader minimum and maximum call bounds against successful and started calls
  respectively.
- Preserve a maximum slot after a failure or uncertain timeout rather than assuming an
  effect did not occur.
- Distinguish complete paths, bounded choices, and impossible paths without exposing a
  public graph API or stable classifier strings.
- Keep unknown type relationships conservative without letting unknown branches erase
  known contradictions.

### 5. Exact database operations

Add optional adapters for prepared operations without exposing database authority:

```text
prepared SQLAlchemy statement or fixed SQLite specification
→ framework-owned adapter and connection/session lifecycle
→ Required(...) or Depends(...) endpoint capability
→ typed callable schema visible to the executor
```

Target declarations will pass the bounded operation object into the endpoint—not a session,
connection, or arbitrary query function:

```python
customer = Required(
    SQLAlchemyOperation(
        statement=customer_select,
        bind={"customer_id": FromRequest("customer_id")},
        output=CustomerView,
    )
)

receipt = Required(
    SQLiteOperation(
        sql=cancel_order_sql,
        bind={"order_id": FromRequest("order_id")},
        output=CancelReceipt,
        exactly_one_row=True,
    )
)
```

- SQLAlchemy `Select`, `Insert`, `Update`, and `Delete` statement objects.
- Fixed parameterized SQLite operation specifications.
- Framework-owned sessions, connections, transactions, and serialization.
- Typed projections and affected-row constraints.
- No raw `Session`, `Engine`, `Connection`, cursor, editable SQL, or natural-language-to-SQL capability.

### 6. Broader deterministic execution compiler

Select the least-powerful sufficient execution path for validated requests whose private
plans contain more than the narrow walking skeleton:

```text
one complete operation path
→ deterministic executor

unresolved legal choice or binding
→ direct agent runtime

no valid path
→ typed deterministic error
```

This decision will use the fixed endpoint goal, validated request, private capability plan,
and validated operation results. Callers will not send an `action` field or select an agent
framework. Endpoint authors will not maintain separate deterministic and agentic handlers
for the same goal:

- A balance endpoint with one exact account lookup and calculation path can run deterministically.
- An order-fulfilment endpoint can run deterministically when only one valid option remains.
- The same order endpoint can use the direct agent runtime when several declared substitutions are valid and a semantic choice remains.
- No executor may add capabilities, weaken validation, or change the response contract.

### 7. Receipts and broader stable failures

Extend the current redacted HTTP handling so authoritative success claims and operation
failures depend on deterministic evidence:

- Typed write receipts.
- Successful-write requirements before accepting success responses.
- Idempotency and transaction policies.
- Typed mappings for authorization, missing records, conflicts, database failures, and exhausted recovery paths, building on the shipped 429/502/504 mappings for usage limits, provider failures, and timeouts.
- Declared recovery paths that cannot expand endpoint authority.

### 8. Optional execution harnesses

Keep the public endpoint contract stable while adding larger internal executors when the request genuinely needs them:

- Direct typed tool loops for normal synchronous endpoints.
- Workspace execution for files, planning, long context, or subagents.
- Durable execution for background, resumable, or long-running work.

Summonpot—not the caller or model—will choose the smallest eligible harness. Changing the harness must never grant additional capabilities.

## Non-goals

- Requiring users to configure agent graphs, chains, planners, or framework-specific agents.
- Turning `@summon` into a traditional handler decorator.
- One endpoint or method for every possible action when one fixed goal can naturally orchestrate bounded capabilities.
- Accepting caller-provided action names as a substitute for endpoint intent.
- Exposing raw database sessions, arbitrary SQL, shell access, filesystem access, or ambient application authority.
- Treating provider-native structured output as a replacement for local validation.

## Design invariant

```text
No declared capability
=
No authority to perform the action
```

The execution harness may evolve. The endpoint's request model, goal, capabilities, and response model remain authoritative.
