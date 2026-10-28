# AGENTS.md — `src/summonpot/`

Rules for changing framework source. The root `AGENTS.md` covers workflow and review;
this file covers the code itself.

## Rules that come from real bugs


Every rule below cost a bug. They are not style preferences.

**Never widen an `except`.** A bare `except Exception` around annotation resolution
silently degraded typed endpoints to untyped ones for months. Catch the exact error you
can handle, and let the rest surface.

**Fail at registration, not at request time.** Roughly ten of 0.3.0's changes turned
silently-wrong declarations into errors raised when the application module is imported.
A wrong declaration should never reach traffic. When adding a rule, add it to
`Summon.__call__()`.

**Do not use a name as a proxy for a property.** Rejecting a capability because its
first parameter is called `self` both rejected valid functions and accepted real
unbound methods with a differently-named receiver. Detect the actual property —
`__qualname__` and the owning class, in that case.

**Do not round-trip a type through a string.** `ParamDef.type_annotation` is a display
string and cannot express `int | None` or `list[int]`. Request schemas are built from
the resolved annotation object; anything that parses a type back out of text is a bug
waiting to happen.

**Respect PEP 563.** This codebase uses `from __future__ import annotations`, so
annotations are strings at runtime and a quoted annotation nests. Two consequences that
have each bitten:

- Resolving once is not enough — `"Request"` evaluates to the *string* `Request`.
- `exec` inherits the future flag from the calling module, so a test that means to
  exclude postponed annotations must `compile(..., dont_inherit=True)`. Without it the
  test asserts the opposite of its name and still passes.

**Preserve `Annotated` metadata.** `typing.get_type_hints` defaults to
`include_extras=False`, and a `Query()` in the default position replaces the
`FieldInfo` an annotation already carried. Both silently drop the user's validation
constraints.

**Never put internal detail in a response body.** Model output and provider text can
carry request data. Failures return a fixed public message; the detail goes to the
`summonpot.server` logger.

**Synchronous capabilities run in a worker thread.** They must not capture a
thread-affine resource — a default SQLite connection is the usual trap. This is also
the one breaking change in 0.3.0 that surfaces under traffic rather than at import.

**Keep the direct-execution predicate exact.** The shipped direct path requires a Pydantic
request model, one required `Exactly(1)` operation, at least one `FromRequest` binding, only
`FromRequest`, authenticated `FromContext` (from 0.13.0), or supported immutable callable defaults, and exact operation-output identity
with the endpoint response model. From 0.12.0, model-free execution also covers uniquely
ordered chains of two or more required `Exactly(1)` operations with the same Pydantic request
and at-least-one-`FromRequest` requirements, only `FromRequest`/`FromResult` bindings or
supported immutable defaults, and an exact full terminal-response annotation. Any
`AgentChoice` remains agent-mediated. Preserve one permitted start per operation per request before application
code. Never describe that local reservation as exactly-once completion, distributed
deduplication, rollback, or cancellation.

From 0.13.0, authenticated `FromContext` also resolves inputs in those admitted single
operations and chains without relaxing request/output eligibility. Snapshot the provider
and immutable canonical principal, preflight every context receiver before effects, keep
context out of model input, and reject unsupported principal validation hooks. HTTP
authentication requires standard `Runtime.call`; context-unused custom runtimes remain
compatible. Context-only declarations remain agent-mediated.

**`functools.wraps` is not enough to describe a capability.** It produces a usable
schema only for a plain function; for a partial or a callable instance it leaves the
provider reading the wrapper's own annotations against the wrong module. Describe the
capability explicitly.

## Reviewing a change

In rough order of what has actually gone wrong here:

- **Does a doc claim something the code does not do?** This project has shipped several
  of these — `stream=True`, "deterministic capabilities", a `method=` that was
  discarded. A claim is a defect.
- **Did the direct-execution predicate widen?** Require registration, runtime, server, and
  packaged-skill tests for every eligibility change. Agent-backed declarations must not enter
  the direct path accidentally, and direct execution must not fall back after it starts.
- **Does a new guard reject valid code?** Every guard added in 0.3.0 needed a
  false-positive test as well as a true-positive one. Two shipped rejecting valid input
  and were caught in review, not by tests.
- **Is the failure at the right time?** Registration beats request time; request time
  beats silence.
- **Does the test fail without the fix?** Assert it. Several tests here have passed for
  the wrong reason — one asserted `"FTER" not in text`, which is also true of `"AFTER"`.
- **Does the response leak anything?** See the rule above.
