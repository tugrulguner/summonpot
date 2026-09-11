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
- Stable OpenAPI `operationId` values derived from each endpoint's declared name and HTTP
  method, with registration-time collision rejection.
- A keyless test model for exercising routing and capability wiring without provider credentials.
- Installable coding-agent skills describing the endpoint contract, typed operation bindings, and the current runtime boundary for Claude Code, Cursor, Windsurf, GitHub Copilot, Cline, and OpenAI Codex.
- Ellipsis declaration bodies that avoid abstract-method semantics, with direct Python calls rejected at the decorator boundary.
- Immutable `Operation` declarations with `FromRequest`, `FromResult`, `FromContext`, and `AgentChoice` argument sources.
- Runtime enforcement for one required `Exactly(1)` operation using `FromRequest`, direct `AgentChoice`, or callable defaults: trusted arguments are hidden and injected, the one start is reserved before invocation, and declared output is locally validated before success.
- Single-operation deterministic execution when the endpoint uses a Pydantic request model,
  that slice has no `AgentChoice`, contains at
  least one `FromRequest` binding, uses only `FromRequest` or immutable identity-stable
  callable defaults, and the operation output is exactly the endpoint response model:
  Summonpot executes directly without resolving or constructing a model.
- Declarative call bounds and ordering references without adding decorator configuration.
- Construction-time validation in `CallBounds`, `Exactly`, `AtLeast`, `AtMost`, and
  `Between` requires non-negative built-in integer counts, excluding booleans, fractions,
  and non-finite values. An absent maximum (`None`) remains valid for unbounded calls;
  this count-type validation does not imply broader runtime call-bound enforcement.
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

### 0.7.0 boundary

Version 0.7.0 activates the first typed operation bindings at runtime. The bound runtime
enforces one required `Exactly(1)` operation whose inputs come from
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
a Pydantic request model and exactly one required `Exactly(1)` operation with at least one `FromRequest` binding, only
`FromRequest` or immutable identity-stable callable defaults, and an operation output exactly
matching the endpoint response model. It runs without resolving, constructing, or calling a model. The broader
multi-operation deterministic compiler remains planned.

Multi-operation graphs, `FromResult`, `FromContext`, `after`, broader call bounds, and
broader no-model execution remain planned. Those unsupported shapes remain on the agent
runtime until their full semantics ship.

### 0.8.0 boundary

Version 0.8.0 gives generated routes stable endpoint-derived OpenAPI `operationId` values,
validates call-bound count types when declarations are constructed, and hardens the
validated HTTP request handoff so compatibility views cannot invoke application copy,
serialization, string, representation, or container hooks against canonical operation
inputs. It preserves safe native query values for agent prompts and custom runtimes while
keeping unsupported values inert.

This release does not broaden runtime enforcement to multi-operation graphs. The remaining
enforce-or-reject, input/output, failure, and deadline semantics stay in milestone 1 below.

## Next milestones

The ordering below prioritizes complete, enforceable contracts before expanding execution.
These are planned acceptance criteria, not claims that the current release enforces them or
promised release dates. The shipped boundaries above remain unchanged until the corresponding
implementation and end-to-end tests land. No milestone adds an executor selection flag,
public graph, or handler body.

### 1. Contract enforcement and input/output hardening

Close the gaps in existing declarations before adding result chains:

- Reject binding sources outside the closed `FromRequest`, `FromResult`, `FromContext`,
  and `AgentChoice` vocabulary at registration.
- Reject unsupported runtime call-bound shapes before serving; broader runtime enforcement
  follows in milestone 5. Construction-time count-type validation is already shipped.
- Enforce every explicitly declared binding, ordering constraint, call bound, and operation
  output contract, or reject the unsupported declaration before serving. Adding a second
  capability must not remove enforcement from an existing operation. Preserve legacy
  model-supplied arguments only for bare capabilities without unsupported explicit constraints;
  do not add a strict-mode switch.
- Define how receiving operation constraints are checked before application code runs,
  without silently transforming canonical bound values or unexpectedly rerunning application
  validators. Request validation alone must not imply compatibility with a narrower operation
  parameter contract.
- Keep canonical validated request values separate from model-facing representations. Remove
  application copy, serialization, and string-rendering hooks from the authoritative handoff;
  render model input only when agent execution needs it. Preserve aliases, defaults, custom
  runtime compatibility, and the validate-once boundary through explicit tests.
- Align raw runtime input validation with HTTP required-field, default, and canonical-value
  semantics, including scalar declarations.
- Prevent output extras and serialization aliases from shadowing validated fields or producing
  duplicate JSON keys. Unsupported output shapes should fail explicitly rather than weakening
  validation. Keep private Pydantic integration isolated and dependency upgrades gated by the
  adversarial suite; do not replace it with a lossy serialization round trip.
- Map operation contract failures to stable redacted HTTP errors. Normal logs must not include
  sensitive validation inputs, provider bodies, or exception chains.
- Define the deadline across request preparation, execution, and finalization; check it before
  starting effects. Document that synchronous application code cannot be forcibly stopped by
  an asyncio timeout and that a timeout does not prove an effect did not occur.

Acceptance requires registration checks and real HTTP probes for the relevant boundaries,
including a second-capability regression, invalid source rejection, unsupported runtime
call-bound rejection, narrower receiving
constraints, mutating serializers, output alias collisions, and sensitive failure logging.
Keep fixes independently reviewable; a copy-hook fix alone is not completion of the transport
boundary.

### 2. Validated result chains and failure semantics

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

Failure semantics ship with the chain, not as a later write-adapter feature:

- Record validated results and distinguish failure before invocation, completed operations,
  partial completion, and an uncertain outcome after timeout.
- Keep failed or uncertain starts reserved; final-output retries must not replay effects.
- Bind authoritative success claims to validated results or typed write receipts. Required
  use alone does not prove that model-authored response claims match an operation result.
- Preserve application-provided idempotency keys and document retry responsibilities. Do not
  imply rollback, endpoint-wide atomicity, or distributed exactly-once completion for arbitrary
  callables.
- Test partial failure and response-validation failure after a successful write.

Execution remains sequential initially. Parallel ready operations are deferred until
idempotency, transaction, or read-only semantics make concurrency safe.

### 3. Producer-constrained agent choices

Constrain `AgentChoice(from_result=...)` to the exact validated collection produced during
the same request:

- Expose only choices from a successful declared producer.
- Use stable internal membership tokens rather than trusting reconstructed model values or
  Python equality.
- Enforce membership locally; generated tool schemas provide guidance, not authority.
- Reject empty or unavailable choice sets deterministically instead of spending model
  retries on an impossible path.

### 4. Authenticated application context

Activate `FromContext` only after the framework has an authenticated, application-owned
context contract:

- Context values come from immutable request-local framework state, never prompt text or
  caller-controlled capability arguments.
- Context types and missing-value behavior are validated before operation invocation.
- Secrets remain hidden from model-visible signatures, schemas, descriptions, and errors.

### 5. Broader bounds and private path classification

Extend the identity-keyed invocation ledger and private plan after the required single-start
slices are stable:

- Enforce broader minimum and maximum call bounds against successful and started calls
  respectively.
- Preserve a maximum slot after a failure or uncertain timeout rather than assuming an
  effect did not occur.
- Distinguish complete paths, bounded choices, and impossible paths without exposing a
  public graph API or stable classifier strings.
- Keep unknown type relationships conservative without letting unknown branches erase
  known contradictions.

### 6. Broader deterministic execution compiler

Select the least-powerful sufficient execution path for validated requests whose private
plans contain more than the narrow walking skeleton:

```text
one complete operation path
→ deterministic executor

unresolved declared agent-owned choice
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

### 7. Exact database operations

Add optional adapters for prepared operations after the common execution and failure
boundaries are stable. Keep application callables sufficient without an adapter. Write
adapters require validated receipts, explicit transaction/commit behavior, and idempotency
policy; validate before committing and do not expose database authority:

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

### 8. Broader receipts and recovery

Build on the minimal receipts, partial-failure handling, and evidence-backed success rules
required by result chains and write adapters. Extend them only for concrete application needs:

- Typed write receipts.
- Successful-write requirements before accepting success responses.
- Idempotency and transaction policies.
- Typed mappings for authorization, missing records, conflicts, database failures, and exhausted recovery paths, building on the shipped 429/502/504 mappings for usage limits, provider failures, and timeouts.
- Declared recovery paths that cannot expand endpoint authority.

### 9. Optional execution harnesses

Defer larger internal executors until concrete applications require them. Keep the public
endpoint contract stable and integrate an established durable engine rather than rebuilding
workflow persistence:

- Direct typed tool loops for normal synchronous endpoints.
- Workspace execution for files, planning, long context, or subagents.
- Durable execution for background, resumable, or long-running work.

Summonpot—not the caller or model—will choose the smallest eligible harness. Changing the harness must never grant additional capabilities.

## Agent execution and context track

This planned track complements the milestones above; it does not turn Summonpot into an
agent-configuration framework. The endpoint body remains `...`: request model, fixed goal,
declared operations and bindings, and response model are still the whole executable contract.
No public `Agent`, graph, planner, memory-manager object, or provider-specific context flags
are required. Reusable application resources are referenced through typed declarations;
Summonpot owns the internal loop, context policy, and execution selection.

The techniques below are not yet shipped Summonpot features. Upstream availability does not
establish compatibility with our pinned dependencies or authority guarantees.

### A. Budgeted working context and bounded agent execution

#### A1. Basic budgeting and context isolation

After milestone 1's boundary hardening, improve the existing agent path without waiting for
milestones 2–3, a general graph, or a durable executor. This early slice does not require
result-chain retrieval or producer-constrained choices:

- Keep canonical request state and the invocation ledger separate from model-visible working
  context. Secrets and the invocation ledger never enter model summaries. This isolation does
  not activate `FromContext` or persistent memory; those retain their later prerequisites.
- Budget the complete model request, including instructions, schemas, retrieved evidence,
  and output/reasoning headroom. Use provider usage and verified deployment limits; unknown
  limits require a conservative operator-approved budget, not a guessed model capacity.
- Start with cheap context selection and deduplication, preserving tool-call/result pairing,
  recent unresolved work, and a protected copy of the fixed contract. If the protected
  context cannot fit, return a bounded failure rather than silently dropping constraints.
  Defer result eviction and result-backed summarization to A2.
- Detect repeated non-progressing model/tool calls and stop within shared turn, token, cost,
  and deadline limits. Extra reasoning or model escalation is internal, operator-bounded,
  evidence-gated, and never restarts effects or changes the endpoint contract.
- Keep a stable contract/schema prefix where provider caching supports it. Treat prompt-cache
  reuse as a cost optimization, never as cross-request memory or authorization.

#### A2. Result-backed context and compaction

Only after validated result chains and producer-constrained choices (milestones 2–3),
extend A1 with result-backed context:

- Keep canonical request/result state separate from model-visible working context and
  persistent memory. `FromContext` is not a prompt-history or memory-injection feature;
  authenticated application context still requires milestone 4.
- Assemble only the relevant, permitted evidence for the next legal decision. Start with
  bounded projections, pagination, and scoped retrieval of declared operation results;
  preserve exact canonical values for `FromResult` and producer-constrained choices.
- Put oversized evidence behind request-scoped opaque handles with bounded reads, provenance,
  expiry, and access checks. No arbitrary filesystem or network authority is added. Do not
  re-execute an effectful operation to recover an evicted tool result.
- Escalate from A1's selection and deduplication to tool-result clearing and then summarization
  only when needed. Preserve tool-call/result pairing, recent unresolved work, exact evidence
  identifiers, and the protected contract; fail boundedly if protected context cannot fit.
- Keep compaction summaries non-authoritative. They cannot reset call reservations, invent
  successful operations, overwrite results, or supply authorization. Preserve exact results
  separately and test repeated compaction and recovery of omitted evidence.

### B. Readiness-aware tool discovery and evidence selection

Build on validated result chains and producer-constrained choices (milestones 2–3):

- Expose or progressively discover only operations already declared and currently legal to
  invoke. Search does not add capabilities, select providers, or authorize an invocation.
  Use eager schemas for small capability sets; defer discovery only when evaluations justify it.
- Recheck readiness, bindings, choice membership, and call limits locally on every invocation,
  including after compaction or provider changes. Re-advertise permitted tools when compaction
  removes their disclosure; never infer availability from stale cached model history.
- Prefer just-in-time retrieval through declared capabilities over loading entire corpora.
  Retrieved text and model-written plans remain untrusted evidence, not executable instructions.
  Retrieval/reranking is replaceable application capability behavior, not a mandatory vector store.
- Use provider-native compaction/search only behind a tested internal adapter. Keep a portable
  path; opaque provider state cannot replace server-owned history or be assumed portable across
  providers. Client-supplied summaries cannot erase authoritative server state.

### C. Optional scoped continuity and persistent memory

Only after authenticated application context (milestone 4), and only for endpoints whose
contract declares continuity or memory access:

- Keep stateless requests the default. Resolve session and memory scope from authenticated
  application state; a client identifier is never sufficient authorization. Isolate tenants,
  users, endpoints, and contract versions, including storage, caches, and retrieval indexes.
- Declare exact memory read/write capabilities with typed records, provenance, freshness,
  retention/deletion rules, and bounded retrieval. Require concurrency-safe updates and
  idempotent writes. Separate read authority from permission to save a model-authored note.
- Label model-authored memories and summaries as untrusted. Corrections and contradictory
  evidence must supersede stale notes; do not promote remembered text into instructions,
  credentials, policy, or proof that an operation completed.
- Keep conversation persistence, memory storage, and durable effect replay distinct. Restoring
  a conversation never authorizes replaying a write. No automatic global notebook, hidden
  cross-user personalization, or model-driven changes to the endpoint's fixed goal.

### D. Isolated delegation and advanced execution experiments

After shared budgets, readiness, and context isolation are proven, evaluate delegation for
workloads where it outperforms a single bounded loop:

- Derive child tasks from the parent's fixed goal and declared capabilities. Give each child
  a minimal context projection, a subset of authority, and typed evidence-backed output;
  children cannot discover undeclared tools or inherit ambient parent credentials.
- Charge child and summarizer work to the same parent budget while enforcing per-child caps,
  depth, total spawned tasks, concurrency, and an absolute deadline. Reserve budget before
  dispatch and account for in-flight overshoot. A child timeout or summary is not proof that
  an external effect was cancelled or completed. Async tool execution requires a final-output
  barrier over pending effects, late-result handling, and explicit cancellation semantics;
  steering cannot change the fixed goal, undo effects, or bypass these checks.
- Verify returned evidence before accepting success. Default to read-only isolated exploration;
  effects still pass through the shared invocation kernel and reservations.
- Keep recursive context processing, model-generated code orchestration, learned memory, and
  multi-agent swarms as benchmark-gated experiments, not default architecture. No generated
  code may bypass declared bindings, output validation, or call limits; no shell or general
  workspace is introduced merely to reduce tokens.

### Evaluation gates for every slice

Compare against the existing single-agent path on representative endpoint tasks. Require
contract and side-effect correctness first; then measure task success, exact identifier and
constraint retention, evidence retrieval, repeated calls, context occupancy, model/summarizer/
child tokens, cache reuse, latency, and cost. Include long runs, repeated compaction, changing
facts, oversized results, budget exhaustion, cross-tenant isolation, prompt injection in
retrieval and memory, and supported-provider parity. Use deterministic assertions for authority
and effects; model judges may supplement semantic-quality evaluation, never replace those checks.
Keep telemetry payload-redacted and version the contract, model, and internal context policy
for reproducible comparisons. No claimed performance gain ships without measured evidence.

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
