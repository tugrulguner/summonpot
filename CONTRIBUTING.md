# Contributing to summonpot

Thanks for helping build summonpot.

## Development setup

```bash
git clone https://github.com/tugrulguner/summonpot.git
cd summonpot
uv sync --all-extras
make check
```

Use `make format` before committing. User-facing changes need a Towncrier fragment named after the pull request:

```text
changelog.d/<pr-number>.<type>.md
```

Supported types are `added`, `changed`, `deprecated`, `removed`, and `fixed`.

## Pull requests

1. Branch from the latest `main`.
2. Keep each pull request focused on one concern.
3. Add or update tests for behavior changes.
4. Add a changelog fragment for user-facing changes, or use `skip-changelog` when the change is not user-facing.
5. Run `make check` and ensure every required GitHub check passes.

## Releasing

The version lives in exactly one place: `version` in `pyproject.toml`. `summonpot.__version__`, `summonpot --version`, generated OpenAPI metadata, and `uv.lock` all derive from that package version. Never edit those derived values by hand.

Use uv to update the single version source and lockfile together:

```bash
uv version 0.2.0
# or
uv version --bump patch
uv version --bump minor
uv version --bump major
```

Then prepare the release notes from the existing Towncrier fragments:

```bash
make changelog-draft
make changelog
make check
```

Open a release pull request containing the `pyproject.toml`, `uv.lock`, generated `CHANGELOG.md`, and fragment removals. After that pull request is reviewed, green, and merged, tag the exact version reported by uv:

```bash
version="$(uv version --short)"
git tag "v${version}"
git push origin "v${version}"
```

The tag triggers `.github/workflows/release.yml`. It reruns CI, verifies that the tag, package metadata, and changelog section all match, builds and inspects the wheel and source distribution, publishes them to PyPI through trusted publishing, and then creates the GitHub Release from the same changelog section with the same artifacts attached.

Nothing in a release is hand-written twice: the version comes from `pyproject.toml`, the lockfile is updated by uv, runtime version surfaces read package metadata, and release notes come from Towncrier and `CHANGELOG.md`.
