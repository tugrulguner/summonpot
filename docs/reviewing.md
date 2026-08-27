# Reviewing a change to Summonpot

Use this guide for local work and pull requests. The code-specific rules in
[`src/summonpot/AGENTS.md`](../src/summonpot/AGENTS.md) are the project criteria; this
document defines the review procedure and evidence expected before a clean verdict.

## 1. Gather the exact change

For a pull request:

```bash
gh pr view <number> --json title,body,state,baseRefName,baseRefOid,headRefName,headRefOid,commits,files,statusCheckRollup
gh pr diff <number>
gh api repos/tugrulguner/summonpot/pulls/<number>/reviews
gh api repos/tugrulguner/summonpot/pulls/<number>/comments
gh api repos/tugrulguner/summonpot/issues/<number>/comments
```

For local work, inspect `git status --short`, the unstaged diff, and the staged diff.
Untracked files are part of the change. Read the touched files and their callers in current
`main` before judging the diff.

## 2. Trace the complete contract

For endpoint changes, follow both paths rather than reviewing one layer in isolation:

```text
signature -> registration validation -> immutable endpoint plan
          -> FastAPI handler/OpenAPI -> Runtime.call -> provider/tool execution
          -> required-operation gate -> local response validation -> HTTP response
```

For a contracted operation, separately trace which values are request-owned, model-owned,
or framework-owned. A trusted value disappearing from the public body is not sufficient if
it remains model-controlled in the tool schema.

## 3. Apply the Summonpot criteria

Prioritize:

- public claims that exceed current runtime behavior;
- guards that reject valid endpoint or capability declarations;
- failures that can be moved from request time to registration;
- mutable caller-owned contract state entering a compiled plan;
- request-local counters or locks accidentally shared between calls;
- bound arguments exposed to model control;
- provider, model, capability, or request detail leaking into public errors;
- broadened execution semantics without matching tests and packaged guidance; and
- public graph, engine-selection, scheduler-control, or configuration surfaces that make the
  endpoint declaration more complex without a proven user need.

Automatic model-free endpoint execution, broader operation graphs, context injection,
receipts, and built-in authentication remain planned unless current source and real execution
prove otherwise. Ordering declarations and their registration-time validation have shipped;
runtime ordering enforcement remains planned.

## 4. Run the checks that matter

Always run:

```bash
make check
make build
git diff --check
```

Then add targeted evidence:

| Changed area | Additional verification |
|---|---|
| endpoint declarations or annotation handling | registration rejection and valid-counterpart tests |
| contracts or binding validation | `tests/test_contract_validation.py` and `tests/test_binding_types.py` |
| runtime or operation enforcement | `tests/test_runtime.py`, including parallel and concurrent-call cases |
| HTTP routing, OpenAPI, or errors | `tests/test_server.py` plus a real `TestClient` request and schema inspection |
| CLI or skill installation | `tests/test_cli.py`, `tests/test_add_skills.py`, and a scratch-directory invocation |
| README, examples, or public vocabulary | docs, examples, skill-content tests, Python-block compilation, and link checks |
| workflows | YAML parse, Actionlint, Zizmor, and reproduction of the exact locked command |
| packaging | wheel/sdist inspection and a fresh installed-artifact smoke test outside the checkout |

A bug test must demonstrate the original failure before the fix. A rejection test also needs
a valid counterpart so a new guard does not overreach.

## 5. Review timeout and side-effect claims carefully

A timeout bounds how long Summonpot waits; it cannot terminate a synchronous capability
already running in a worker thread. `Exactly(1)` reserves at most one operation start in the
supported bound shape; it is not distributed exactly-once completion. Do not approve stronger
wording without transaction, idempotency, retry, and cancellation evidence.

## 6. Review the built artifact

Build one wheel and one source distribution, inspect their contents, and install the wheel in
a fresh environment outside the repository. Verify representative public imports, CLI
version output, packaged coding-agent guidance, one HTTP route, request validation, and the
complete OpenAPI operation. A fake runtime proves packaging and transport wiring; it does not
prove a live provider round trip.

## 7. Verify findings and report against the exact head

Execute a reproducer when possible. Before trusting a negative check, break the relevant
condition and prove the check goes red. Classify findings:

- **High** — correctness, security, authority-boundary failure, secret/detail leakage, or a
  false public claim; blocks merge.
- **Medium** — an important design inconsistency, unsupported scope expansion, or missing
  acceptance coverage; should fix.
- **Low** — an optional improvement.

Post findings against `headRefOid`, read the review and inline comments back from GitHub, then
re-fetch the head. A clean verdict requires green checks on that exact SHA and a pull-request
description that still matches the final implementation.
