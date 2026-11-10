# One prefix selection before a repeated stage (included from version 0.15.0)

One endpoint can find application-approved candidates, select/prepare one, perform bounded
checks, verify its facts and persist a canonical report. Summonpot owns progression through
these operations; the application declares the dataflow and owns business policy. No handler
loop, execution-mode parameter, public graph or new declaration syntax is required.

This extends the [resolved-neighbor single-stage form](stage-chains.added.md). Published
v0.14.0 is unchanged. This composition is not part of that public release.

## Admission

- A Pydantic request with at least one `FromRequest` across the complete chain; supported
  request/result/authenticated-context bindings and immutable defaults.
- A uniquely ordered chain of required operations, independent of declaration order.
- Exactly one nonterminal repeated operation with positive finite effective bounds,
  `minimum >= 1`, `maximum > 1`, and existing direct closed plain-string `Literal` choices.
- Exactly one producer-backed `AgentChoice(from_result=producer)` argument on one required
  `Exactly(1)` consumer before the repeated operation. Its earlier single-start producer
  returns the existing supported `list[ConcreteModel]`; item-type metadata and canonical
  receiving constraints remain enforced.
- All other operations are required `Exactly(1)` and fully resolved. There is no second
  prefix choice argument/frontier, choice inside repetition or choice in the suffix.
- Ordinary `FromResult` addresses single-start producers. Every repeated-result reference
  requires `invocation="final"`, with at least one suffix consumer. Closure and one terminal
  exact full response owner remain mandatory; repeated output stays a distinct intermediate.

Unresolved/external references, unsupported item types, cycles, ambiguous readiness, duplicate
identities, additional repeated stages and ambiguous response ownership reject before serving.
Existing standalone producer-choice progression and stage declarations retain their semantics.

## Runtime and authority

Unsupported explicit function-tool quotas reject inside runtime admission before authentication
or application effects. Existing HTTP transport validation is unchanged. Authentication runs
once; all context receiving constraints, including suffix-only constraints, preflight before
application/model work. Raw-runtime request preparation retains its existing boundary.

The candidate producer runs before domain validation and model lookup. Empty, unavailable or
oversized domains retain the established fixed unavailable-choice response before the selection
consumer or repeated stage starts. Current candidate/evidence caps apply to singleton paths too.
A singleton binds locally through the same token membership, receiving and reservation checks.
Ambiguous candidates use strict request-local opaque tokens and bounded inert evidence. The
consumer receives the exact validated ledger member, never a model reconstruction or an
object admitted by equality. Candidate freshness/authorization at effect time is application policy.

The trusted model configuration is looked up once, lazily at ambiguous selection or at the
repeated stage after singleton selection. That specification is reused. This is not a guarantee
of one SDK adapter instance: decision selectors may construct separate Agents. A singleton skips
only selection inference; the repeated stage still requires model decisions. Neither selector
has business-function tools or endpoint-completion authority.

One run, principal, ledger, absolute deadline, effective limits and request/token/cost usage
span selection, correction attempts, repetition and suffix. Selector calls never reset endpoint
budgets. The fixed goal and current decision task remain understandable in each phase without
implicitly projecting canonical selected objects, prefix state, authentication data or ledger.
The existing safe request and bounded previous repeated-result projections remain; application
outputs may intentionally disclose permitted facts. Evidence caps are not a complete context budget.

Selected consumer output flows through declared bindings to later operations. Legal finish or
automatic maximum creates the same immutable repeated-stage closure; minimum success alone
never enables suffix work. Final bindings read one pinned producer/ordinal/canonical result.
Verification and finalization run without further model decisions or acknowledgment, and only
the terminal operation's canonical validated output owns the response.

## Failure boundaries

Within one invocation, a later failure never triggers supplier reselection, effect replay,
reopening a closed stage or returning an earlier successful snapshot. Failed/cancelled/uncertain
starts retain reservations; minima count validated successes, maxima count starts. Prefix and
selection effects can precede provider failure; check or final writes can precede a later error.
No rollback, endpoint-wide transaction or durable resume is implied.

A fresh HTTP request starts a fresh run, queries candidates again and may select differently.
Application-owned idempotency and stored check collections remain separate from runtime provenance.

## Example and deferrals

Example 17 (`examples/17_choice_stage/`) demonstrates candidate identity all the way through
checks, verification and independently read-back SQLite report persistence. Different supplier
facts yield different policy outcomes, and incomplete checks deny approval. Examples 1–16
remain unchanged. Scripted selectors test protocol/authority; real-provider selection quality
requires separate live semantic acceptance.

Multiple prefix choices, producer-backed choices inside or after repetition, choices from
repeated outputs, multiple/nested stages, feedback cycles, aggregation, optional/unbounded
stages, parallel scheduling, database adapters and durable recovery remain deferred.
