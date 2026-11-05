# Bounded checkpoint progression (unreleased implementation)

One endpoint can declare a bounded sequence that checks application state, performs
permitted continuation work only while that check is negative, and returns one
canonical application result. Summonpot owns progression; application functions do
not call each other or maintain a handoff loop. This is an unreleased source
capability, not behavior of published v0.14.0.

The completion declaration is `Required(check, calls=Between(1, M), until="accepted")`.
It is an explicit execution contract, not a general loop primitive or a hint to a
model. The marker names a stored strict Boolean field in the check's validated
output. Only exact `True` closes accepted; exact `False` permits another declared
continuation, or closes at the declared limit. A negative business result is still
a successful, validated operation invocation.

```text
required region → checkpoint
                    ├─ true ─────────────────────────→ terminal
                    ├─ last allowed false ────────────→ terminal
                    └─ false → negative continuation → next required region
```

No inspection/discovery/correction business roles or fixed operation count are
recognized. A three-operation status/refresh declaration and a longer cleanup
sequence use the same private region semantics. Operation identities, bindings,
ordering and effective bounds establish the regions, independently of endpoint
parameter names or declaration order.

## Complete admission boundary

- Pydantic request/response contracts and at least one `FromRequest` in the required
  region. Other resolved inputs use supported request, same-round results,
  authenticated context or admitted immutable defaults.
- Exactly one `until` marker on a required typed operation. Its canonical field name
  must be an exact nonempty string naming a stored, non-null strict Boolean field;
  aliases, property/computed fields, expressions and coercive Boolean schemas are
  not completion declarations. `until=None` retains ordinary Required semantics.
- A uniquely ordered required region ends at that operation. Every required-region
  operation has effective bounds `1..M`, where `M >= 2` is finite.
- A nonempty, uniquely ordered optional negative continuation has effective bounds
  `0..M-1` per operation. Its dependencies connect it to the current checkpoint;
  its arguments may use admitted same-round/request/context/default sources and
  bounded `AgentChoice` inputs. Direct closed string-valued Literal choices and
  existing producer-backed concrete-model choices retain local authority checks.
- One required `Exactly(1)` terminal uniquely declares the endpoint's exact full
  response annotation. Its result bindings read only fields from the checkpoint
  with `FromResult(check, "field", invocation="final")`; it cannot require the
  optional continuation to have executed. Supported request/context/default
  inputs remain allowed.
- All operation identities and argument sources are resolved and validated before
  serving. Ambiguous/disconnected/cyclic graphs, duplicate identities, inconsistent
  bounds, unsupported crossings or multiple checkpoints reject registration.
  Invalid marked declarations never fall through to a weaker agent/direct route.

This contract supports stateful re-inspection, not using a continuation receipt as
an implicit next-round input. It adds no public graph, workflow configuration,
strategy, role labels or caller-selected mode. Existing unmarked single-operation,
chain, producer-choice and repeated-stage contracts keep their behavior.

## Progression and authority

The required region runs first. If the checkpoint is true, continuation is skipped.
If it is false before the last allowed check, the negative continuation runs once,
then a new required round re-reads state through the declared operations. At the
Mth false check, no additional continuation starts: the checkpoint closes and the
terminal can produce an application-owned unresolved result.

Deterministic operations progress locally. The agent is asked only for unresolved
bounded argument choices, never whether to approve, finish or invoke a known next
operation. Singleton candidate domains bind canonical members locally without a
model. An empty candidate domain fails closed with the existing choice-unavailable
boundary; it does not fabricate acceptance or automatically run terminal. Invalid,
unavailable or oversized evidence is also a failure, not a normal negative result.

Request/context admission occurs once. One principal, ledger, inference usage policy
and absolute deadline cover all rounds and terminal execution. Model configuration
is resolved lazily only if an ambiguous choice needs it, then retained for the run.
Context/results are not implicitly disclosed to the model; permitted application
projections can intentionally expose evidence.

Same-round references identify exact validated producer invocations, not a global
latest-result slot. A final selector reads one immutable closed checkpoint result.
Every terminal field comes from that same closing invocation. The endpoint returns
the terminal's validated canonical result, not the checkpoint, model text or an
earlier successful response.

## Limits, concurrency and failure

Maxima count starts; minima count validated successes. The marked optional operations
are framework-scheduled conditional steps, not business tools the model may schedule
freely. Only one frame operation may be in flight. Continuation admission retires its
round's choice/closure authority atomically with reservation; closure and admission
cannot both win. Only a fresh successful check after the entire prior continuation
can authorize accepted or limit closure.

Selection-output corrections consume the same inference budget and retain one fixed
candidate domain. They do not rerun producers or retry application effects. Failed,
cancelled, invalid-output and uncertain starts remain consumed. The run aborts after
abnormal failure; no later operation, old-result fallback, model handoff or replay is
allowed. An already-running synchronous worker may complete an external write later,
but cannot reopen the aborted run or publish new execution authority.

A correction may commit before a later check or terminal fails; a terminal may commit
a report before the request fails. No response does not mean no effect. A fresh HTTP
request starts a new run and is not safe/idempotent unless the application establishes
that policy. No rollback, endpoint-wide transaction, durable resume or recovery is
implied. Application transactions/revision guards, not tokens or closure, establish
external database consistency.

The application owns approval/status policy and actual report persistence. The
framework enforces canonical bindings, bounds, validated outputs and terminal
ownership; exact response typing alone does not prove business truthfulness.

Unsupported explicit function-tool quotas reject this marked shape before effects,
including a request that might otherwise close without inference. The contract is
not a direct optimization: `allow_direct=False` must not disable its enforcement.

## Separate examples and evidence

- Example 18 demonstrates stateful cleanup with canonical candidate membership and
  actual guarded writes followed by revision-checked report persistence.
- Example 19 demonstrates status/refresh with a direct closed Literal choice and
  fewer operations. Already-accepted state needs neither refresh nor inference.

Existing examples remain separate and unchanged. Source unit/protocol tests, real
localhost HTTP effects, real-provider semantics, installed-artifact qualification
and matched performance measurements are different evidence layers. A keyless
FunctionModel test is not a paid-provider run; an in-process HTTP client is not
public-CLI/live-server acceptance. No package release is implied by source work.
