# AGENTS.md

Working notes for anyone — human or agent — changing summonpot.

For *using* summonpot, run `summonpot add skills`; that installs the endpoint contract
as a skill. This file is about developing the framework itself.

## What summonpot is

A contract-first API framework. An endpoint declaration is the executable contract:

```text
request model + docstring goal + declared capabilities + response model
```

The ellipsis is a complete declaration body, not an unfinished implementation. The
decorated declaration rejects direct calls. Today every request runs through the
provider-neutral agent runtime; the target is a compiler that picks the least-powerful
sufficient executor, skipping the model entirely when one legal path remains.

Two invariants govern almost every design argument:

1. **The endpoint declaration is the whole contract.** Anything that pushes configuration
   outside the endpoint declaration is moving in the wrong direction.
2. **No executor may add capabilities, weaken validation, or change the response
   contract.**

## Layout

```text
src/summonpot/
  summon.py            @summon, registration and all registration-time guards
  runtime.py        the agent loop, model resolution, usage limits and timeout
  server.py         FastAPI route construction, request schemas, HTTP error mapping
  models.py         EndpointDef, ToolDef, ParamDef
  dependencies.py   Depends / Required
  tools.py          capability construction from callables
  _annotations.py   shared annotation resolution (used by summon.py and tools.py)
  cli.py            the summonpot command
  commands/         CLI subcommands
  skills/           the shipped agent skill, and per-agent formatting
  templates/skills/ the skill body itself
```

## Coding guidelines

Rules for changing framework source — including the ones that each cost a real bug —
live in [`src/summonpot/AGENTS.md`](src/summonpot/AGENTS.md). Agents read the nearest
file in the directory tree, so editing source picks them up automatically.

## Workflow

```bash
uv sync --all-extras          # setup
make check                    # lint, format, typecheck, tests
make format                   # before committing
```

Every user-facing change needs a Towncrier fragment. Use the tracking issue number when one
exists:

```text
changelog.d/<issue-number>.<type>.md
```

For a small direct change without an issue, generate a unique orphan fragment:

```bash
uv run towncrier create +.changed.md
```

Dependabot is exempt, by label. Anything else without a fragment fails a required check
unless it carries `skip-changelog`.

Two things `make check` will not catch:

- **Workflow YAML.** A `: ` inside an unquoted scalar breaks a workflow and nothing in
  the test suite notices. Parse the file after editing it.
- **Deleted tests.** A green suite says nothing about tests that no longer exist. After
  any conflict resolution, diff the test-function inventory against the parent branch.

## Stacked pull requests

Long chains are normal here. Two things to know:

- **Squash-merging a parent orphans its children.** The child still carries the
  parent's original commits, which no longer match the squashed one. Fix by replaying
  only the child's own commits: `git rebase --onto origin/main <old-parent-tip> <branch>`.
  Prefer merge commits for chains.
- **Do not resolve conflicts by keeping both sides mechanically.** It works for imports
  and pure appends, and silently splices function bodies together everywhere else.

## Keeping the docs honest

`README.md`, `ROADMAP.md`, `docs/`, and the shipped skill in
`src/summonpot/templates/skills/` all describe behaviour. When behaviour changes, they
change in the same pull request.

The skill is enforced: `tests/test_skills_content.py` pins the rules it must keep
documenting, so a framework change that contradicts it fails the suite. Shipped
documentation that can go stale silently is worse than none.
