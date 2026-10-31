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
execution for the narrow complete path shipped below; admitted declarations with a direct
semantic choice and bare legacy capabilities use the agent runtime. For the enforced single
required `Exactly(1)` slice, Summonpot hides and injects application-owned arguments and
leaves only declared `AgentChoice` values to the agent.
Unsupported explicit contract shapes fail during registration until their full semantics
ship. Bare `Depends(fn)` and `Required(fn)` declarations remain compatible with implicit
marker bounds and no explicit `Operation` contract. The typed HTTP endpoint stays stable as
that balance changes.

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
- Stable redacted failure handling: malformed HTTP requests and receiving-operation input failures return fixed `422` responses; invalid operation output, model/provider failures, timeouts, and application failures keep distinct status categories. Normal logs use allowlisted endpoint/failure fields only and omit exception text/chains, provider bodies, validation input, prompts, output, and capability data. This is failure-boundary hardening only; it does not redesign deadlines or add result chains.
- GET, POST, PUT, PATCH, DELETE, and HEAD routing with validated body or query contracts.
- Stable OpenAPI `operationId` values derived from each endpoint's declared name and HTTP
  method, with registration-time collision rejection.
- A keyless test model for exercising routing and capability wiring without provider credentials.
- Installable coding-agent skills describing the endpoint contract, typed operation bindings, and the current runtime boundary for Claude Code, Cursor, Windsurf, GitHub Copilot, Cline, and OpenAI Codex.
- Ellipsis declaration bodies that avoid abstract-method semantics, with direct Python calls rejected at the decorator boundary.
- Immutable `Operation` declarations with `FromRequest`, `FromResult`, `FromContext`, and `AgentChoice` argument sources.
- Runtime enforcement for one required `Exactly(1)` operation using `FromRequest`, direct `AgentChoice`, or callable defaults: trusted arguments are hidden and injected, the one start is reserved before invocation, and declared output is locally validated before success.
- Receiving-operation constraint validation is shipped for injected `FromRequest` values in
  that supported direct and agent-backed slice. The runtime checks each receiving operation
  parameter strictly before application code, rejects coercion, preserves the canonical
  validated request value, and does not rerun request-model validators. The closed hook-free
  vocabulary accepts finite Decimal values and non-pattern string length constraints while
  rejecting non-finite bare Decimals, Decimal `allow_inf_nan=True`, callable discriminators,
  and string patterns at registration.
- Single-operation deterministic execution when the endpoint uses a Pydantic request model,
  that slice has no `AgentChoice`, contains at
  least one `FromRequest` binding, uses `FromRequest`, authenticated `FromContext` (from 0.13.0), or immutable identity-stable
  callable defaults, and the operation output is exactly the endpoint response model:
  Summonpot executes directly without resolving or constructing a model.
- Declarative call bounds and ordering references without adding decorator configuration.
- Construction-time validation in `CallBounds`, `Exactly`, `AtLeast`, `AtMost`, and
  `Between` requires non-negative built-in integer counts, excluding booleans, fractions,
  and non-finite values. An absent maximum (`None`) remains valid for unbounded calls;
  this count-type validation does not imply broader runtime call-bound enforcement.
- Registration-time validation for complete bindings, request and result references, operation ordering, selectable collections, and provable type incompatibility.
- Fail-closed runtime admission: binding sources must use the exact built-in source
  vocabulary, and every explicit binding, ordering, call-bound, and output contract must fit
  supported single-operation or uniquely ordered sequential required `Exactly(1)` shape,
  or registration rejects it. Adding another capability cannot downgrade that contract to
  the legacy path.
- Structural output-namespace validation rejects duplicate field, alias, serialization-alias,
  and computed-field JSON keys at registration, including nested model, dataclass, and typed
  dictionary shapes. Runtime output validation rejects allowed extras that shadow canonical
  field names or emitted aliases while retaining noncolliding validated extras.
- Python 3.11-3.14 CI, package builds, and expanded runtime/CLI coverage.

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
broader no-model execution remained planned at this release boundary. Later boundaries
below record the subsequently enforced shapes.

### 0.8.0 boundary

Version 0.8.0 gives generated routes stable endpoint-derived OpenAPI `operationId` values,
validates call-bound count types when declarations are constructed, and hardens the
validated HTTP request handoff so compatibility views cannot invoke application copy,
serialization, string, representation, or container hooks against canonical operation
inputs. It preserves safe native query values for agent prompts and custom runtimes while
keeping unsupported values inert. Runtime-enforced output schemas also reject ambiguous
declared or extra-owned JSON keys without serializing application values.

This release does not broaden runtime enforcement to multi-operation graphs. The remaining
result-chain and broader deterministic-execution semantics stay in milestone 2 below.

This release line completed the admission portion of that milestone: only one required typed
operation with `calls=Exactly(1)`, complete supported bindings, declared output, no ordering,
and no second capability is admitted. `FromRequest` and direct `AgentChoice` are the only
runtime-supported binding sources. All other explicit shapes fail before serving; bare
callable dependencies retain their implicit marker behavior.

### 0.9.0 boundary

Version 0.9.0 completes fail-closed runtime admission for explicit capability contracts in
the shipped single-operation slice, validates receiving operation constraints before
application code starts, and hardens declared and runtime output namespaces against
ambiguous or duplicate emitted keys. Unsupported explicit shapes are rejected during
registration rather than downgraded to the legacy model-supplied path.

Raw runtime mappings use the declared request contract for the same required-field, default,
alias, and canonical-value semantics as HTTP without rerunning the HTTP adapter's one-shot
validation. Parameterless endpoints compile an explicit empty raw contract, rejecting
undeclared keys before application hooks or model execution.

Version 0.9.0 did not ship stable failure-boundary handling or end-to-end runtime deadline
semantics; those were still milestone 1 acceptance criteria. It did not add result chains or
broader deterministic execution.

### 0.10.0 boundary

Version 0.10.0 completes milestone 1's single-operation contract and input/output hardening.
It ships stable redacted failure responses and one monotonic runtime deadline spanning request
preparation, execution, and finalization, with pre-effect checks. HTTP body parsing, request
validation, and response serialization are outside that deadline. Synchronous preparation,
finalization, and capability work cannot be preempted; a timeout after synchronous work starts
does not prove that an effect did not occur. These guarantees do not add result chains, broader
deterministic execution, or claim context budgeting.

### 0.11.0 boundary: sequential operation chains

Version 0.11.0 added agent-mediated sequential chains of two or more required `Exactly(1)` operations, provided exactly one operation is ready at every step.
`FromResult` injects fields from a predecessor's locally validated Pydantic result;
`after` independently requires successful predecessor completion. Declaration order does
not choose execution order. Operations use `FromRequest`, `FromResult`, supported immutable
callable defaults, and producer-backed `AgentChoice(from_result=...)` only when the producer
declares `list[ConcreteModel]`. Chains with `FromContext`, broader bounds, disconnected
nodes, cycles, or any step with multiple ready operations remain unsupported. Choice
projection and local token authority are described in milestone 3 below.

Exactly one operation must declare the endpoint's exact full response annotation, and it
must be the terminal operation. The endpoint returns that canonical validated result,
not model-authored success claims. Models see completion acknowledgments and bounded inert evidence for declared
choices, not canonical intermediate result objects. They still orchestrate this slice; no-model multi-operation execution
remains planned.

Call maxima count starts; required minima count validated successes. Failed, cancelled,
or uncertain starts retain their reservations. Model retries never replay those effects.
This does not provide rollback or distributed exactly-once effects; cross-request retries
need application idempotency. The runnable [inventory example](examples/10_result_chain/README.md)
uses real application-owned SQLite operations and persisted receipts, not a framework adapter.

Version 0.11.0 completes this subset of milestone 2, not the broader milestone. Historical v0.10.0 does not include it.

### 0.12.0 boundary: model-free resolved chains

From version 0.12.0, a Pydantic request endpoint executes a uniquely ordered chain of required `Exactly(1)` operations directly when the chain is fully resolved. The chain has at least two operations, exactly one required `Exactly(1)` operation is ready at each step, and every argument resolves through `FromRequest`, validated `FromResult`, or supported immutable callable defaults. At least one `FromRequest` binding is required. The terminal operation declares the endpoint's exact full response annotation, and its validated result is returned unchanged. No model is resolved or constructed, and there is no fallback after execution starts. Any `AgentChoice`, including producer-backed choices, keeps the chain agent-mediated. Unsupported shapes remain rejected. Historical v0.11.0 chains remain agent-mediated.

### 0.13.0 boundary: authenticated application context

Authenticated context is included from version 0.13.0 through `Summon(context=authenticate)` and canonical `FromContext` bindings
to the admitted single required `Exactly(1)` operation and uniquely ordered required
`Exactly(1)` chain shapes. The application verifies credentials and returns a frozen,
closed Pydantic principal with supported immutable fields. Principal admission is a
non-transforming structural check; unsupported validation/lifecycle hooks and transforming
configuration are rejected instead of changing an authenticated identity.

The provider is captured at registration, runs once for each declared HTTP endpoint request
inside the runtime deadline after transport validation, and protects endpoints even without
a context binding. Documentation/OpenAPI routes are outside this hook. Authentication denial
returns fixed 401; invalid context or unexpected provider failures return fixed redacted 500.
All context receiving constraints, including later chain steps, are preflighted before any
operation or model starts. The context snapshot is request-local and hidden from model input;
application outputs can intentionally disclose values and remain application-owned.

Authenticated `FromContext` can join a fully resolved model-free path, but the existing
Pydantic request, at-least-one-`FromRequest`, immutable-default, and exact terminal response
requirements remain. `AgentChoice` stays agent-mediated. Raw `Runtime.call(...,
context=principal)` is trusted server code only; authenticated HTTP requires standard
`Runtime.call` admission and rejects replacement call methods. Login, authorization,
tenant-scoped database queries, cross-request idempotency, and transactions remain
application responsibilities. Broader bounds, graphs, adapters, recovery, and persistent
memory remain planned. Historical 0.12.0 does not include authenticated context.

### 0.14.0 boundary: result-dependent execution with one producer-backed choice

Version 0.14.0 includes the narrow single-choice result-dependent optimization described below. It requires an otherwise eligible uniquely ordered required `Exactly(1)` chain, a Pydantic request with at least one `FromRequest` binding, exactly one producer-backed choice and no other choice, supported immutable defaults and request/result/authenticated-context bindings, and exact full terminal response annotation identity. Historical v0.13.0 behavior remains agent-mediated for every producer-backed choice.

## Current source, not yet released

The current source implements an unreleased framework-owned progression slice across one or more producer-backed choices in an otherwise eligible uniquely ordered chain. Eligibility remains a Pydantic request with at least one `FromRequest`, at least two required `Exactly(1)` operations, supported request/result/authenticated-context bindings or immutable defaults, and exact full terminal response annotation identity. The selector receives only a safe request projection and bounded inert evidence for the current ambiguous binding(s); it has no business-function tools, principal or ledger. Every current consumer domain is checked before selecting or starting that consumer. Singleton choices bind canonical members locally; ambiguous bindings are selected together from strict opaque-token slots, then the shared invocation kernel validates and invokes the consumer. The framework-owned progression continues locally through singleton frontiers and returns the canonical validated terminal result without model-authored completion. All frontiers and corrections share request/token/cost usage, effective limits and one deadline; the model resolves once, lazily, at first ambiguity. Explicit `tool_calls_limit` and `allow_direct=False` preserve the legacy route. This producer-choice chain route adds no durable cross-request resume, rollback, effect replay, repeated calls, general graph compiler or public selector. This is a partial milestone 3 implementation, not milestone completion and not a published v0.14.0 behavior. Bounds remain 128 candidates and 65,536 evidence characters per binding. Prefix effects may precede provider-configuration failure; there is no rollback or cross-request replay guarantee.

## Next milestones

The ordering below prioritizes complete, enforceable contracts before expanding execution.
These are planned acceptance criteria, not claims that the current release enforces them or
promised release dates. Milestone 1 was completed in the 0.10.0 boundary. The release boundaries
above complete the narrow milestone 2 slice for 0.14.0; broader orchestration and graph work
remain planned. No milestone adds an executor selection flag,
public graph, or handler body.

### 1. Contract enforcement and input/output hardening

Completed in 0.10.0: the 0.9.0 admission, transport, and namespace work plus the failure and
runtime-deadline guarantees recorded in the 0.10.0 boundary above. This completion does not
include response serialization in the deadline or claim preemption of synchronous work.

No remaining acceptance criteria are listed for this completed milestone. Follow-on result-chain
work begins at milestone 2.

### 2. Result-dependent execution with one producer-backed choice

Completed in 0.14.0 (included from version 0.14.0): the narrow result-dependent optimization for one producer-backed choice in an otherwise eligible sequential chain. The 0.11.0, 0.12.0, and 0.13.0 boundaries above retain their historical semantics; in particular, published v0.13.0 chains with producer-backed choices remain agent-mediated, including singleton domains. The unreleased source extension below is separate and does not alter those historical release boundaries.

The shipped 0.14.0 contract uses `FromResult` to pass only a producer's locally validated output into a downstream operation; the data dependency establishes result readiness. The terminal operation remains the explicit final-response producer and returns its canonical validated result.
The complete chain is eligible only in the supported linear required-operation shape; there is no public maximum chain length.
Exactly one producer-backed choice using `AgentChoice(from_result=producer)` is supported in the eligible linear required-`Exactly(1)` chain, with producer output `list[ConcreteModel]`. Selection remains scoped to the complete eligible chain, not a separately exposed subgraph.
Every uniquely ready prefix operation executes before model resolution. If a producer returns no candidates, the existing fixed redacted unavailable-choice response occurs before model resolution or downstream work.
For exactly one candidate, Summonpot selects the canonical validated member locally and continues without resolving or constructing a model.
For multiple candidates, the configured model resolves lazily at that choice boundary; only bounded inert descriptions and opaque request-local tokens are exposed, with local membership verification before binding the exact canonical candidate.
On the singleton path the fully resolved suffix executes without a model. With multiple candidates, the suffix continues through the existing agent-mediated chain in the same run. The terminal operation remains the canonical final-response producer; model-authored success claims are not a substitute.
Eligibility requires a Pydantic request with at least one `FromRequest` binding, an existing uniquely ordered chain of at least two required `Exactly(1)` operations, exactly one producer-backed choice argument across the chain and no other choice, supported immutable defaults plus request/result/authenticated-context bindings, and exact full terminal response annotation identity. The producer must return the supported concrete-model list and precede the consumer. This narrows optimization eligibility only; all other admitted declarations keep their existing agent-mediated route. The 128-candidate and 65,536-character evidence limits apply even to singleton domains, and local selection passes canonical-member and receiving checks.
The same authenticated context, validated request, results, reservations, stable tokens and absolute deadline carry across the model handoff. The prefix is not replayed and model history is not fabricated. Prefix effects may precede provider-configuration failure on the multiple-candidate path; lazy model resolution does not make the prefix side-effect-free or provide rollback.
Bare callable capabilities and supported explicit declarations outside this optimization retain their existing agent-mediated path. Unsupported explicit contracts remain rejected at registration.
Regression coverage verifies zero candidates, singleton execution with zero model resolution/construction/calls, and multiple candidates using the same endpoint/provider; producer effects precede model resolution, model resolution occurs only once for multiple candidates, and token forgery, stale tokens, output failure, timeout and downstream failure cannot authorize or replay effects.

This 0.14.0 optimization does not alter the historical v0.11.0, v0.12.0, or v0.13.0 boundaries: each retains its historical behavior, including agent mediation for producer-backed choices. Outside this narrow optimization eligibility, the existing supported agent-mediated execution is preserved. No recurring bounds, rollback, cross-request idempotency, or endpoint-wide transactions are introduced.

### 3. Bounded orchestration with multiple choices and repeated calls

The current source implements framework-owned producer-choice progression and a narrow sole-operation slice of finite repeated calls. This milestone is **partially implemented, not complete**. Both additions are unreleased; historical version boundaries above remain unchanged.

The repeated-call slice covers one required typed operation with a Pydantic request, at least one `FromRequest`, direct closed string-valued `Literal` choices, supported request/context sources or immutable defaults, exact full operation-output/endpoint-response annotation identity, and positive finite effective bounds. Summonpot owns the sequential loop, reserves starts before application code, counts validated successes for the minimum, retains per-invocation identity/results and failed or uncertain reservations, and returns the final successful canonical invocation result after legal finish or automatic maximum completion. Any later failure aborts; an earlier success is not a fallback response. Explicit function-tool quotas reject this new shape before work rather than silently weakening limits.

The remaining work is specifically **repeated-result addressing and orchestration in chains**, not basic sole-operation repetition:

- Define which producer invocation each `FromResult` receiver or producer-backed choice refers to. Do not silently read a mutable latest-result slot, infer aggregation, or let a model invent provenance.
- Extend readiness and ordering to repeated producers/consumers only after those result references are explicit. Enforce declared minimum and maximum call bounds against validated successes and starts respectively; retain reservations for failed, cancelled, or uncertain starts. Model retries cannot replay an effect or change the fixed endpoint goal.
- Require one unambiguous terminal operation/result, including its invocation identity, and exact response ownership for repeated chains. Keep model-owned stopping choices separate from model-authored success claims.
- Exercise repeated producer domains, empty/unavailable sets, bound exhaustion and failures between consumers, with exact result-to-consumer provenance and shared request-wide budgets.
- Keep execution sequential until concurrency, partial completion and timeout uncertainty, and cancellation have explicit semantics. Recovery must not replay an uncertain effect.

No optional/zero-success or unbounded execution, implicit batch, general graph compiler, parallel scheduling, durable execution, rollback, or distributed exactly-once effects are added by the completed narrow slice. Existing `Required` marker normalization remains unchanged: its effective minimum is at least one.

### 4. Broader private execution compiler

- Extend private compilation beyond the required single-start slices only after milestone 3 settles invocation and result semantics. Preserve the least-powerful sufficient execution rule:

```text
one complete legal path → deterministic execution
bounded declared choice → agent-mediated execution
no legal path → typed deterministic error
```

- Compile complete paths, unresolved choices, and impossible paths across supported non-linear dependency shapes without exposing a public graph API or stable classifier strings.
- Keep argument and result provenance identity-keyed; validate operation outputs before consumption and use exact terminal response annotations.
- Use conservative compatibility analysis: unknown type relationships remain unknown and cannot erase known contradictions.
- Keep the runtime/compiler private. Callers do not select a path, send `action`, or gain capabilities through compilation.
- Test branched dependencies, joins, cycles, disconnected operations, incompatible and unknown types, no-legal-path errors, deterministic zero-model paths, and choice-bearing agent paths.

No public graph API, arbitrary parallel scheduling, or handler-side orchestration is part of this milestone.

### 5. Exact bounded database operations and transaction boundaries

Add optional adapters only after execution and result semantics are stable. Application callables remain sufficient without an adapter. A target object flow is:

```text
prepared SQLAlchemy statement or fixed SQLite specification
→ framework-owned adapter and session/connection lifecycle
→ Required(...) or Depends(...) endpoint capability
→ typed operation result or write receipt
```

- Accept only exact prepared SQLAlchemy `Select`, `Insert`, `Update`, or `Delete` statement objects and fixed parameterized SQLite specifications; bind only declared parameters from validated request/result sources.
- Return typed projections and constrained affected-row receipts. Never expose raw `Session`, `Engine`, `Connection`, cursor, editable SQL, or natural-language-to-SQL authority.
- Define read lifecycle and write transaction boundaries explicitly: when a transaction begins, validates, commits, and rolls back; which failures are known pre-commit versus uncertain after commit; and how output validation relates to commit.
- Make adapter ownership, connection/session cleanup, and transaction propagation explicit. Do not imply a cross-capability transaction unless the contract actually provides one.
- Test bounded predicates and bind values, row-count constraints, output validation, commit/rollback boundaries, cleanup, cancellation, and commit uncertainty.

Adapters are optional; they do not make arbitrary callables transactional or confer cross-request idempotency.

### 6. Concrete recovery and long-running execution

Build on explicit result semantics and transaction boundaries to support concrete recovery or long-running workloads. Do not build a generic durable workflow layer in advance of a demonstrated endpoint need.

- Record invocation identity, validated completed results, failed starts, and uncertainty durably when a declared execution mode requires resumption.
- Define idempotency keys and deduplication scope, checkpoint ownership, retry eligibility, cancellation, late results, and recovery authority. A timeout or worker cancellation is not proof that an external effect stopped.
- Resume only from authoritative recorded results; never replay an uncertain effect without an application-defined idempotency/reconciliation decision.
- Keep recovery paths within the endpoint's original declared capability set and exact response contract. Define typed outcomes for missing records, conflicts, authorization failures, adapter failures, and exhausted recovery.
- Test process interruption around effect/record boundaries, duplicate delivery, concurrent resume, stale checkpoints, partial completion, and unknown outcomes.

This milestone does not promise distributed exactly-once effects. Transactionality, idempotency, and recovery guarantees must be stated at their actual scope.

### 7. Optional execution harnesses

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

With milestone 1's boundary hardening now complete in 0.10.0, improve the existing agent path
without waiting for milestones 2–3, a general graph, or a durable executor. This early slice does not require
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

Only after broader orchestration (milestone 3),
extend A1 with result-backed context:

- Keep canonical request/result state separate from model-visible working context and
  persistent memory. `FromContext` is not a prompt-history or memory-injection feature;
  authenticated application context is already available under the 0.13.0 boundary above.
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

Build on broader orchestration (milestone 3):

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

Only after authenticated application context is available (included from 0.13.0), and only for endpoints whose
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
