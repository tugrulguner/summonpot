# Repeated stage with final-result consumer (current source, unreleased)

This is a narrow source capability, not a release claim: one bounded repeated producer
closes, then one required terminal operation consumes its explicitly addressed final
validated result. Published v0.14.0 is unchanged. The inspect/correct/verify workflow is not
implemented by this shape.

```python
FromResult(checks, "audit_id", invocation="final")
FromResult(checks, "findings", invocation="final")
```

`invocation` is keyword-only and currently accepts only `"final"`. It denotes the final
successful invocation of a closed repeated stage, not the latest result of an open stage.
The producer identity, selected invocation ordinal, and canonical validated output are held
in one immutable closure record; every selected field resolves from that same record. An
unqualified `FromResult(op, field)` retains its existing single-invocation semantics and is
rejected when `op` is repeated. There is no arbitrary ordinal, `latest`, aggregation, or
model-selected provenance.

## Admission

- Exactly two required typed operations: the repeated producer and a uniquely ordered,
  required `Exactly(1)` terminal consumer. The result dependency establishes readiness;
  any `after` edge must be consistent.
- The producer has positive finite effective bounds (`minimum >= 1`, `maximum > 1`), a
  Pydantic request with at least one `FromRequest`, direct plain-string `Literal` choices,
  and supported request/context bindings or immutable defaults. Its Pydantic output is an
  intermediate type, distinct from the endpoint response.
- The terminal has exactly one terminal ownership role, no choices, and consumes at least
  one `FromResult(producer, field, invocation="final")`. Other bindings use supported
  request/context/default sources. Its exact full output annotation is the endpoint's
  response annotation.
- Repeated producers without explicit final addressing, selectors other than `"final"`,
  selector use on a single-call producer, multiple terminals, incompatible receiving types,
  cycles, multiple repeated stages, extra capabilities, and unsupported mixed contracts
  are rejected.
- Existing sole-operation repetition, ordinary uniquely ordered `Exactly(1)` chains, and
  producer-choice declarations retain their prior supported behavior; no downgrade or
  semantic reinterpretation is intended.

## Closure and execution boundary

The terminal is not ready merely because the producer met its minimum. Closure is legal only
when no invocation is running, the effective minimum of validated successes is met, and the
selected final invocation succeeded. The model may choose legal finish, or reaching the
maximum closes automatically without another model acknowledgment. The closure is immutable;
no later producer start can retarget it. All final-field bindings use this same closure
record, including when field declaration order differs.

A failed, cancelled, or uncertain invocation after an earlier success aborts the endpoint;
there is no fallback to an earlier invocation. The terminal runs once through the shared
kernel after receiving constraints and readiness/deadline checks. The endpoint returns its
canonical validated result, not the repeated snapshot or model-authored completion. Existing
request-wide usage accounting and deadline remain shared; no per-stage reset is introduced.
The repeated shape rejects explicit function-tool quotas rather than inventing accounting.

This boundary does **not** add repeated consumers, producer-backed choices from repeated
outputs, arbitrary invocation selection, result aggregation, optional/zero-success or
unbounded stages, multiple repeated operations, general graphs, cycles, parallelism,
durable resumption, rollback, distributed exactly-once effects, or a complete
inspect/correct/verify workflow. Application-owned SQL and cumulative snapshot policy remain
application concerns. The feature is unreleased current source and does not alter v0.14.0.
