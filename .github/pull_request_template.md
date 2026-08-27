## Summary

Describe the current behavior and the focused change in this pull request.

## Related issue

Use `Closes #<issue-number>` when this work has an agreed issue. Write `Not applicable` only for a small documentation, test, maintenance, or clearly scoped bug fix that did not need one.

<!-- Closes #123 -->

## Scope and non-goals

State what this change deliberately does not add. Keep public API, runtime-authority, and execution-model changes inside the agreed issue scope.

## User-visible behavior

Describe what changes for a Summonpot user. Write `None` for maintenance-only work.

## Verification

- [ ] Added or updated tests that fail without the fix when behavior changed.
- [ ] Verified the real HTTP, OpenAPI, CLI, or installed-package surface when applicable.
- [ ] `make check`
- [ ] `make build`
- [ ] Completed the relevant checks in `docs/reviewing.md`.

List the exact commands run and their results:

```text

```

## Documentation and contracts

- [ ] Updated README, roadmap, examples, or packaged coding-agent guidance when their public contract changed.
- [ ] Kept current shipped behavior separate from planned architecture.
- [ ] Preserved registration-time validation, redacted public errors, and framework-owned bound arguments where applicable.
- [ ] Avoided adding public graph, engine-selection, scheduler-control, or fat decorator configuration APIs.

## Changelog

- [ ] Added `changelog.d/<pull-request-number>.<type>.md` for a user-facing change; or
- [ ] This has no user-visible effect and should receive the `skip-changelog` label.

## Safety

- [ ] No API keys, tokens, credentials, connection strings, private request data, or provider output are included in this pull request.
