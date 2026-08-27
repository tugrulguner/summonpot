# Changelog fragments

Each unreleased user-facing change is one file in this directory.

When the change has a tracking issue, use its number:

```text
<issue-number>.<type>.md
```

For a small direct change without an issue, create a unique orphan fragment:

```bash
uv run towncrier create +.changed.md
```

Replace `changed` with the appropriate type. Supported types are `added`, `changed`,
`deprecated`, `removed`, and `fixed`.

Write one sentence about the effect for a user. Example:

```text
42.added.md -> Add typed request binding to endpoint declarations.
```

Numeric fragments link to their GitHub issue in the assembled changelog. Orphan fragments
remain unlinked. Do not edit `CHANGELOG.md` directly. `make changelog-draft` previews the
assembled release; `make changelog` builds it during release preparation. Internal-only work
may use the `skip-changelog` label with maintainer approval.
