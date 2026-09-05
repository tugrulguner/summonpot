# Contributing to Summonpot

Thanks for helping build Summonpot as a contract-first Python API framework.

## Choose the right path

- Use the [bug report form](https://github.com/tugrulguner/summonpot/issues/new?template=bug.yml)
  for reproducible failures.
- Open a
  [feature request](https://github.com/tugrulguner/summonpot/issues/new?template=feature.yml)
  before substantial public API, capability-authority, runtime, provider, or execution-model
  work. Align on the contract before implementing it.
- Small documentation, test, maintenance, and clearly scoped bug fixes may go directly to a
  pull request.
- Use [GitHub Discussions](https://github.com/tugrulguner/summonpot/discussions) for usage
  questions and early ideas that are not ready to become scoped work.

Search open issues and pull requests before starting. If an issue is labeled `good first
issue` or `help wanted`, comment and wait for confirmation before implementation so two
contributors do not solve the same problem.

## Development setup

```bash
git clone https://github.com/tugrulguner/summonpot.git
cd summonpot
uv sync --all-extras
uv run pre-commit install
make check
```

Use `make format` before committing.

## What a change must preserve

- `Summon` and `@summon(...)` remain a minimal endpoint declaration, not a graph builder or
  execution-engine configuration surface.
- One fully resolved required `Exactly(1)` operation with complete `FromRequest` or
  callable-default bindings and exact output identity executes directly without a model.
  Every declaration outside that narrow shipped slice remains model-backed.
- Registration rejects invalid declarations before traffic when the failure is knowable.
- In the shipped single-required-operation `Exactly(1)` slice, supported `FromRequest`, direct
  `AgentChoice`, and callable-default bindings are framework-owned rather than model-controlled.
- Unsupported binding shapes, including `FromContext`, remain model-supplied.
- Provider text, model output, capability details, credentials, and private request data do
  not enter public error bodies, fixtures, issue reports, or pull requests.
- Public contract changes update README, roadmap, examples, and packaged coding-agent
  guidance together when those surfaces are affected.

The rules in [`src/summonpot/AGENTS.md`](src/summonpot/AGENTS.md) come from real bugs and are
review requirements rather than style preferences.

## Tests and review evidence

Run the complete gate:

```bash
make check
make build
```

Behavior changes need a regression test that fails without the fix and a valid-counterpart
test when adding a new rejection. HTTP and OpenAPI changes need real request/schema coverage;
CLI changes need an invocation in a scratch project; package changes need a fresh
installed-artifact smoke test outside the checkout.

[`docs/reviewing.md`](docs/reviewing.md) defines the targeted suites, artifact checks, and
exact-head review procedure used by maintainers.

## Pull requests

1. Branch from the latest `main`.
2. Link the agreed issue with `Closes #<issue-number>` when one exists.
3. Keep one concern per pull request and stay inside the agreed scope.
4. Add or update tests and executable examples when behavior changes.
5. Synchronize affected public documentation and packaged guidance.
6. Add an issue-numbered changelog fragment for tracked user-facing work, or generate a
   unique orphan fragment for a small direct change.
7. Run `make check`, `make build`, and the relevant checks in `docs/reviewing.md`.
8. Open the pull request with current behavior, focused change, non-goals, and exact
   verification results. Leave it open for review.

## Changelog fragments

User-facing changes require one Towncrier fragment. When the change has a tracking issue,
use its number:

```text
changelog.d/<issue-number>.<type>.md
```

For a small direct change without an issue, let Towncrier create a unique orphan fragment:

```bash
uv run towncrier create +.changed.md
```

Types are `added`, `changed`, `deprecated`, `removed`, and `fixed`. Write one sentence about
what changed for a user, not how the patch was implemented. Numeric fragments link to their
GitHub issue; generated orphan fragments remain unlinked. Run `make changelog-draft` to
preview the result. Do not edit `CHANGELOG.md` directly. For maintenance with no user-visible
effect, a maintainer may apply the `skip-changelog` label.

## Reporting issues

Search existing issues and pull requests first. A useful bug report includes the installed
version or exact source revision, Python and operating-system versions, provider/model or the
keyless test model, a minimal complete endpoint, the exact request or command, and observed
versus expected behavior.

Remove API keys, tokens, credentials, connection strings, private request data, and provider
output before posting publicly.

For substantial public API, runtime-authority, provider, capability-contract, or execution
changes, open an issue and align on the smallest contract before implementation.

## Releasing

Releases are prepared by maintainers. The only hand-edited version is `version` in
`pyproject.toml`; use `uv version` so package metadata and `uv.lock` stay synchronized.
Runtime and CLI version surfaces derive from installed package metadata.

Maintainers assemble release notes from existing Towncrier fragments with:

```bash
make changelog-draft
make changelog
make check
```

After the release pull request is reviewed, green, and merged, its exact version tag triggers
`.github/workflows/release.yml`, which verifies the version/changelog contract, builds and
inspects artifacts, publishes through trusted publishing, and creates the GitHub Release.
