---
name: "pr-review"
description: "Handle the mechanics of a summonpot pull request: changelog fragments, stacked branches, restacking after a squash-merged parent, verifying no tests were lost, and reading review comments already addressed. Use when opening, updating, rebasing, or landing a pull request."
---

# summonpot pull request mechanics

## Opening one

Every user-facing change needs a Towncrier fragment. When the change has a tracking issue,
use its number:

```text
changelog.d/<issue-number>.<type>.md
```

For a small direct change without an issue, generate a unique orphan fragment before opening
the pull request:

```bash
uv run towncrier create +.changed.md
```

Replace `changed` with `added`, `deprecated`, `removed`, or `fixed` when appropriate. Numeric
fragments must name an issue, not a pull request. Non-user-facing changes carry the
`skip-changelog` label instead. Dependabot is exempt by label already.

Do not add Claude co-author trailers or "Generated with" lines to commits or PR bodies.

## Stacked branches

Chains are normal here. Base each PR on its parent, not on `main`.

**CI only runs on PRs targeting `main`.** A stacked PR shows one green check — the
changelog one — and its real CI fires when it is retargeted after its parent merges.
Run `make check` locally and say so in the PR.

## After a parent is squash-merged

The child still carries the parent's original commits, which no longer match the
squashed commit on `main`, so GitHub reports conflicts. Do not resolve them — replay
only the child's own commits:

```bash
git log --oneline origin/main..origin/<child>     # find the old parent tip
git rebase --onto origin/main <old-parent-tip> <child>
```

Prefer merge commits for chains, which keeps SHAs and avoids this entirely.

## Resolving conflicts

Keeping both sides mechanically works for import blocks and pure appends. Everywhere
else it splices function bodies together and produces code that still parses. It has
silently deleted five tests in this repo.

After any conflict resolution:

```bash
python3 - <<'PY'
import re, subprocess, pathlib, glob
def names(s): return set(re.findall(r"^def (test_\w+)", s, re.M))
for f in glob.glob("tests/test_*.py"):
    base = subprocess.run(["git","show",f"origin/main:{f}"],capture_output=True,text=True).stdout
    if base:
        lost = names(base) - names(pathlib.Path(f).read_text())
        if lost: print(f, sorted(lost))
PY
```

A passing suite proves nothing about tests that no longer exist.

## Reading review comments

Comments predating your last push are usually already addressed. Compare timestamps
before acting:

```bash
git log -1 --format=%cI origin/<branch>
gh api "repos/<owner>/<repo>/pulls/<N>/comments" --jq '.[]|"\(.created_at) \(.path)"'
```

When the reviewing account is also the PR author, GitHub records reviews as
`COMMENTED` rather than `APPROVED` — the verdict is in the comment text, not the badge.

Reproduce a reported defect before fixing it, and say so in the reply. Several reports
in this repo have been correct in the defect but wrong in the cause, and one was not
reproducible at all.
