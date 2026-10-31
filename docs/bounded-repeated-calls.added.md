# Bounded repeated calls — unreleased source contract

The minimum here is the effective bound after marker normalization: existing `Required(op, calls=AtMost(3))` still requires at least one successful call. Zero-success/optional shapes remain unsupported; the marker is not redefined.


This source-only addition is limited to one explicitly required, typed operation with finite positive `Exactly(n)` or `Between(minimum, maximum)` bounds satisfying `1 <= minimum <= maximum` and `maximum > 1`. Its endpoint has a Pydantic request with at least one `FromRequest` binding, at least one direct `AgentChoice` typed as a closed set of `Literal[str]` choices, supported remaining request/context bindings or immutable defaults, and exact full operation-output/endpoint-response annotation identity. No `Depends` operation, second capability, producer choice, `FromResult`, `after`, mixed exactly-once chain, zero minimum, unbounded shape, inferred iteration, implicit batch, or general graph is added. In particular: no `FromResult`, no `after`, no `Depends`, no implicit batch, zero minimum is excluded, unbounded shape is excluded, and no general graph is introduced. Existing exactly-once operation/chain and producer-choice paths retain their behavior.

Summonpot owns the sequential loop and enforces legal finish decisions; application operations are never business function tools for the selector. Every decision is validated locally against the closed choice contract before a reserved start. Maximum bounds reserved starts, minimum counts validated successful outputs. Finish before minimum successes is rejected; after minimum it is legal. When maximum is reached, execution finalizes automatically without a model acknowledgment. Shared request usage (`RunUsage` and effective `UsageLimits`) and one absolute deadline cover every decision and correction; model resolution is lazy and once.

The response is exactly the canonical validated result of the final successful invocation. It is not a collector or aggregate. Any invocation/input/output failure aborts the endpoint, with no fallback to an earlier success. A failure after an earlier side effect is not rolled back. A later HTTP request is a new run.

The new shape rejects an explicit `tool_calls_limit` before provider resolution and application operations; there is no repeated-call fallback. The existing Exactly(1) compatibility route and explicit prior behavior remain unchanged. Existing context preflight remains as-is, except invalid tool quota is rejected before authentication/provider work.

Previous-result evidence is bounded to 65,536 characters per decision; this is not an aggregate prompt budget. The selector may see caller request data and bounded declared evidence intentionally used for its choice. It receives no implicit principal or complete invocation ledger.

The implementation is partial milestone 3, not a finished milestone. Repeated-result addressing for chains remains next. No behavior, version, dependency, or release claim is made for published v0.14.0.
