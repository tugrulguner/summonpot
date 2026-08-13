# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as fragment files in [`changelog.d/`](changelog.d/) until a
release assembles them here — run `make changelog-draft` to preview them.

<!-- towncrier release notes start -->

## [0.2.0] - 2026-08-12

### Added

- Add first-class Pydantic request and response contracts with provider-neutral structured output, tool execution, HTTP validation, OpenAPI schemas, and locally validated runtime results. ([#8](https://github.com/tugrulguner/summonpot/pull/8))
- Add declarative `Depends` and runtime-enforced `Required` operations so endpoint signatures define a closed deterministic capability set without handler code or extra HTTP fields. ([#9](https://github.com/tugrulguner/summonpot/pull/9))
- Expand runtime, deterministic operation, and CLI test coverage, including mandatory capability omission and exact command-line failure diagnostics. ([#10](https://github.com/tugrulguner/summonpot/pull/10))
- Document the shipped declarative capability model and publish the roadmap for typed operations, database adapters, execution selection, receipts, stable failures, and optional larger harnesses. ([#11](https://github.com/tugrulguner/summonpot/pull/11))
- Document deterministic and agentic endpoint execution modes, decision rules, examples, and the current status of automatic execution selection. ([#13](https://github.com/tugrulguner/summonpot/pull/13))
- Lead with the signature-only, no-handler endpoint contract for unified deterministic and agentic execution, and document planned SQLAlchemy and SQLite capability adapters with restricted database-operation examples. ([#14](https://github.com/tugrulguner/summonpot/pull/14))

### Fixed

- Stop exposing summonpot's internal endpoint and runtime closure state as query parameters in generated OpenAPI schemas. ([#7](https://github.com/tugrulguner/summonpot/pull/7))
- Correct README examples and terminology to use real application-owned capabilities consistently and remove placeholder operations and unimplemented streaming claims. ([#12](https://github.com/tugrulguner/summonpot/pull/12))


## [0.1.0] - 2026-08-10

### Added

- Add continuous integration, packaging, changelog tooling, and developer Makefile targets. ([#1](https://github.com/tugrulguner/summonpot/pull/1))
- Add the initial summonpot framework with agentic API endpoints, automatic request schemas, tool calling, OpenAI-compatible model providers, CLI serving, and generated OpenAPI documentation. ([#2](https://github.com/tugrulguner/summonpot/pull/2))

### Changed

- Add comprehensive framework documentation, quick-start instructions, and usage examples. ([#3](https://github.com/tugrulguner/summonpot/pull/3))
- Add release automation, dependency updates, pull-request labeling, and stale issue management. ([#4](https://github.com/tugrulguner/summonpot/pull/4))

### Fixed

- OpenAPI metadata now derives its version from installed package metadata, keeping `pyproject.toml` as the single source updated by `uv version`. ([#5](https://github.com/tugrulguner/summonpot/pull/5))
