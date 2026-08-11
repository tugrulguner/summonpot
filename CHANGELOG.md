# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as fragment files in [`changelog.d/`](changelog.d/) until a
release assembles them here — run `make changelog-draft` to preview them.

<!-- towncrier release notes start -->

## [0.1.0] - 2026-08-10

### Added

- Add continuous integration, packaging, changelog tooling, and developer Makefile targets. ([#1](https://github.com/tugrulguner/summonpot/pull/1))
- Add the initial summonpot framework with agentic API endpoints, automatic request schemas, tool calling, OpenAI-compatible model providers, CLI serving, and generated OpenAPI documentation. ([#2](https://github.com/tugrulguner/summonpot/pull/2))

### Changed

- Add comprehensive framework documentation, quick-start instructions, and usage examples. ([#3](https://github.com/tugrulguner/summonpot/pull/3))
- Add release automation, dependency updates, pull-request labeling, and stale issue management. ([#4](https://github.com/tugrulguner/summonpot/pull/4))

### Fixed

- OpenAPI metadata now derives its version from installed package metadata, keeping `pyproject.toml` as the single source updated by `uv version`. ([#5](https://github.com/tugrulguner/summonpot/pull/5))
