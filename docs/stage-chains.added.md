# One repeated stage in a sequential chain (current source, unreleased)

Summonpot can own a uniquely ordered chain with one nonterminal bounded repeated operation,
a resolved prefix, and a nonempty resolved suffix. This composes preparation and deterministic
verification/finalization with bounded agent-owned decisions, without handler-side loops or a
new graph/configuration API. Published v0.14.0 is unchanged.

```text
prepare → bounded checks → verify → finalize
```

The original two-operation repeated producer/terminal form remains supported as a zero-prefix,
one-consumer case. Sole-operation repetition, resolved `Exactly(1)` chains and producer-choice
progression retain their existing execution semantics.

## Complete admission predicate

- Pydantic request and response; at least one `FromRequest` across the whole chain. The
  repeated operation need not duplicate a request binding when it receives prepared values.
- Exactly one required repeated operation, positive finite effective bounds
  (`1 <= minimum <= maximum`, `maximum > 1`), and at least one direct closed plain-string
  `Literal` choice. Other inputs use supported request/result/authenticated-context bindings
  or immutable defaults. Existing `Required` minimum normalization is unchanged.
- Every other operation is required `Exactly(1)` and fully resolved, with no agent choices.
  A prefix is optional; a suffix and terminal response operation are required. No public
  maximum chain length is imposed.
- Identity-keyed data and `after` dependencies establish exactly one ready operation at
  each step, independent of declaration order. Redundant earlier dependencies are allowed.
- Single-invocation results use ordinary `FromResult(op, "field")`. Every reference to the
  repeated producer uses `FromResult(op, "field", invocation="final")`; at least one suffix
  operation must consume that pinned result. Later suffix operations may consume both
  earlier ordinary results and the same closed-stage result.
- The repeated output is a supported Pydantic intermediate distinct from the endpoint
  response. Exactly one operation declares the endpoint's exact full response annotation,
  and that operation is terminal.

Missing request bindings, unsupported sources/defaults/annotations, external choices, repeated
terminals, multiple repeated stages, invalid selectors, self references, disconnected or
multiple-ready dependencies, cycles and ambiguous response ownership reject before serving.
This is not general graph admission or a producer-choice/repeated-stage combination.

## Runtime ownership

Request/context admission happens once. All authenticated-context receiving constraints,
including suffix-only constraints, are preflighted before prefix effects. Unsupported explicit
function-tool quotas also fail before authentication, prefix work or model resolution.

The shared guarded kernel runs the resolved prefix without resolving a model. One model is
resolved lazily when the repeated stage is reached. Its decision-only selector has no
business-operation tools or endpoint-completion authority. All prefix-result inputs are
validated at each receiving invocation before start reservation. Ordinary prefix results,
context and the ledger are not automatically projected into model prompts; the existing safe
request and bounded previous-result evidence policy remains, and application outputs may
intentionally disclose permitted facts. Evidence caps are not a complete context budget.

Legal finish or automatic maximum closes the stage only after its required validated successes,
with no running invocation and a final successful invocation. Minimum success alone never
readies successors. One immutable closure record pins producer identity, invocation ordinal
and canonical validated result. All final-result consumers read that record, not a mutable
latest-result slot, and closure forbids further producer starts. `after` dependencies on the
repeated operation also require closure.

The resolved suffix runs in the same request without further model decisions or final model
acknowledgment. Each start passes receiving, predecessor, deadline and reservation checks.
The endpoint returns the terminal operation's canonical validated result, never a model-authored
success claim or an earlier repeated snapshot.

One request-local principal, ledger, absolute deadline and effective request/token/cost usage
span prefix, repeated decisions and suffix. Corrections charge the same usage budget; the
existing retry policy remains. There is no boundary reset or recursive endpoint call.
Call maxima count starts and minima count validated successes. Failed, cancelled or uncertain
starts retain reservations; model retries do not replay effects.

Prefix effects can precede missing-provider failure. Suffix failures can follow already committed
checks or earlier suffix writes. No earlier-success fallback, rollback, endpoint-wide transaction,
framework idempotency or durable resume is implied. A fresh HTTP request starts a fresh run;
application-owned persistence and cross-request policies remain separate.

## Example and limits

[Example 16](../examples/16_stage_chain/README.md) loads an order, performs bounded stock/price
checks, deterministically verifies the required business facts, and persists/read-backs the
final review report. An incomplete or failed check cannot be turned into approval by model
text. Stored check collections and report policy are application-owned, not framework aggregation.
Existing examples 1-15 are unchanged.

No feedback cycles, inspect/correct/verify retry workflow, repeated consumers, choices outside
the repeated operation, producer-backed choices from repeated outputs, arbitrary ordinal/latest
addressing, result aggregation, multiple/nested repeated stages, optional/unbounded stages,
parallel scheduling, durable recovery, database adapters or distributed exactly-once effects
are introduced. Milestone 3 remains partial. This is current source, not a v0.14.0 release claim.
