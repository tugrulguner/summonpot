# summonpot roadmap

summonpot is building toward one endpoint contract:

```text
Pydantic request model
+ fixed endpoint goal
+ exact deterministic capabilities
+ Pydantic response model
= executable agentic endpoint
```

The endpoint body is declarative and is never the handler. Request JSON carries business data, not an action selector. The agent may orchestrate only the capabilities declared by the endpoint.

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
- Python 3.11–3.13 CI, package builds, and expanded runtime/CLI coverage.

## Next milestones

The ordering below reflects technical dependencies, not promised release dates.

### 1. Typed capability contracts

Move from function signatures alone to explicit operation contracts:

- Validate capability inputs before execution.
- Validate capability outputs before they enter agent context.
- Declare minimum and maximum call counts.
- Support once-only operations and required ordering.
- Restrict each argument to declared sources: request data, prior operation results, framework context, or explicitly agent-controlled values.

### 2. Exact database operations

Add optional adapters for prepared operations without exposing database authority:

- SQLAlchemy `Select`, `Insert`, `Update`, and `Delete` statement objects.
- Fixed parameterized SQLite operation specifications.
- Framework-owned sessions, connections, transactions, and serialization.
- Typed projections and affected-row constraints.
- No raw `Session`, `Engine`, `Connection`, cursor, editable SQL, or natural-language-to-SQL capability.

### 3. Deterministic execution compiler

Select the least-powerful sufficient execution path for each validated request:

```text
one complete operation path
→ deterministic executor

unresolved legal choice or binding
→ direct agent runtime

no valid path
→ typed deterministic error
```

This decision will use the fixed endpoint goal, validated request, capability graph, and operation results. Callers will not send an `action` field or select an agent framework.

### 4. Receipts and stable failures

Make authoritative success claims depend on deterministic evidence:

- Typed write receipts.
- Successful-write requirements before accepting success responses.
- Idempotency and transaction policies.
- Stable HTTP mapping for validation, authorization, missing records, conflicts, provider failures, database failures, and exhausted model retries.
- Declared recovery paths that cannot expand endpoint authority.

### 5. Optional execution harnesses

Keep the public endpoint contract stable while adding larger internal executors when the request genuinely needs them:

- Direct typed tool loops for normal synchronous endpoints.
- Workspace execution for files, planning, long context, or subagents.
- Durable execution for background, resumable, or long-running work.

Summonpot—not the caller or model—will choose the smallest eligible harness. Changing the harness must never grant additional capabilities.

## Non-goals

- Requiring users to configure agent graphs, chains, planners, or framework-specific agents.
- Turning `@pot.summon` into a traditional handler decorator.
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
