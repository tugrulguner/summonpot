# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as fragment files in [`changelog.d/`](changelog.d/) until a
release assembles them here — run `make changelog-draft` to preview them.

<!-- towncrier release notes start -->

## [0.13.0] - 2026-10-28

### Added

- Add application-authenticated request context through `Summon(context=authenticate)` and canonical `FromContext` bindings. Typed immutable principals are request-local, snapshotted before execution, hidden from model inputs, and preflighted across admitted single operations and uniquely ordered chains before effects. HTTP authentication runs within runtime deadlines; trusted Python callers may explicitly supply an already authenticated principal. Includes a runnable tenant-scoped SQLite notes example with verified bearer credentials, persisted receipts, and idempotency.


## [0.12.0] - 2026-10-26

### Added

- Add model-free execution for fully resolved sequential required `Exactly(1)` chains with a Pydantic request, at least one `FromRequest` binding, uniquely ordered readiness, only supported `FromRequest`/`FromResult` sources or immutable callable defaults, and an exact full terminal response annotation. Return the validated canonical terminal result without resolving or constructing a model. Any `AgentChoice` keeps the chain agent-mediated; historical v0.11.0 chains remain agent-mediated.
- Add the validated producer-choice chain diagram after the existing overview in the README, homepage, and execution internals guide. Include the rendered PNG and deterministic SVG renderer; preserve the existing diagrams and artwork byte-for-byte.


## [0.11.0] - 2026-10-22

### Added

- Add agent-mediated sequential required-operation chains, validated `FromResult` injection, enforced `after` ordering, and SQLite inventory examples. Return the canonical validated terminal result instead of model-authored success claims. Failed, cancelled, and uncertain starts retain their reservations; model retries cannot replay effects. Applications retain responsibility for cross-request idempotency and transactions.
- Add producer-constrained `AgentChoice(from_result=...)` to uniquely ordered sequential `Required(..., calls=Exactly(1))` chains. Choices come only from a successful producer's locally validated `list[ConcreteModel]`; the model sees opaque request-local tokens and inert projected candidate descriptions, never canonical results. Selection maps back to the exact validated member without trusting Python equality. Candidate sets are limited to 128 items and 65,536 JSON characters per binding; empty, unavailable, and oversized sets fail with a fixed redacted 409 before model decision or downstream work, with no extra model request. This remains agent-mediated, not model-free; direct single-operation `AgentChoice` behavior is unchanged. Primitive/untyped collections, direct unbounded choices in chains, context, broader bounds, and general graphs remain unsupported. The historical v0.10.0 release is unchanged.
- Support validated sequential operation chains of two or more steps with exactly one ready operation at every step. Broader graph execution, context, and recovery remain planned.

### Changed

- Add accessible social links and a product-specific feedback route to the Summonpot website.
- Clarify the endpoint contract and framework-owned orchestration across the README, roadmap, and website. Distinguish the validated terminal result and agent-mediated sequential-chain slice from the broader deferred model-free compiler.
- Match Summonpot’s wordmark suffix to the existing flask violet across canonical, raster, social, and website header branding.

### Fixed

- Add the standalone playground's missing canonical URL, favicon, and Open Graph/Twitter sharing metadata while preserving its browser-local behavior and existing artwork.
- Keep a direct, clearly labeled Feedback action visible in compact navigation, while retaining ModePot in the menu and keeping feedback context limited to the canonical public page.
- Keep personal GitHub, LinkedIn and X links beside the creator attribution with restrained text sizing instead of crowding project navigation.
- Keep the Summonpot wordmark prefix off-white and use the final flask-matched violet suffix consistently across the README, website, and social artwork.
- Make the quick-start HTTP example runnable with the installed console command and explicit environment and example-download steps.
- Stabilize the narrow mobile header during custom-element initialization and prevent the 320px wordmark from overlapping Search. The bounded-operation preview now announces readiness, busy, and completed states, and keeps Run disabled until its client controller is ready.
- Update website and Python dependencies to address the open Dependabot advisories and the additional certifi advisory found during independent audit. Run pre-commit in an isolated tool environment with patched virtualenv so its packaging requirement does not conflict with the xAI SDK.


## [0.10.0] - 2026-10-13

### Added

- Add a product website with documentation and agent-readable discovery files.

### Changed

- Add a bounded browser-local quote contract playground and remove the recorded demo viewer/fixtures. The playground is explicitly illustrative; the separate direct HTTP example remains the executable framework path.
- Add a compact Summonpot family mark for small-size brand and package contexts.
- Add a complete homepage endpoint example showing bounded agent choice and a required application-owned operation.
- Adds a secondary Roadmap action to the homepage hero when the repository roadmap source is present.
- Adds privacy-safe browser-local playground outcome events. The shared `playground_preview_started` / `playground_preview_completed` contract includes only bounded project, mode, result, failure class, and an ephemeral per-attempt correlation ID; it excludes request values and output. No library telemetry was added.
- Align the Summonpot homepage with the reviewed framework landing composition while preserving its existing playground and documentation.
- Center the Summonpot homepage content at desktop and mobile widths, and link to its standalone browser-local playground instead of embedding it in the landing page.
- Clarify the browser-local bound-operation playground with a request/choice/operation authority flow, canonical shipped Python source, compact results, aligned controls, and restrained accessible colors.
- Expand the documentation with task guides for the supported model-free and agent-backed operation paths, an operation/binding reference, execution internals, and provider troubleshooting. Generate downloadable Markdown from the same guide sources and index the new routes in the website navigation and llms.txt.
- Instrument summonpot.modepot.io with privacy-conscious shared ModePot PostHog page analytics.
- Normalize Summonpot homepage, documentation, and standalone and embedded playground controls to the ModePot family typography, layout, spacing, and purple-accent presentation while preserving the framework's native Light, Dark, and Auto themes and the browser-local, shipped-example authority boundary.
- One monotonic deadline now covers runtime request preparation, execution, and final output validation. Synchronous preparation and validation remain non-preemptible; HTTP body parsing/request validation precede the handler and are outside this runtime deadline. A capability already running in a synchronous worker may still complete after timeout, so treat timeout as an uncertain outcome and use application-level idempotency for irreversible effects.
- Operation input/output contract failures now map to stable redacted HTTP responses, and normal failure logs omit exception text and chains. Malformed request-validation responses no longer echo rejected values. Deadline semantics and result chains are unchanged.
- Preserve `Annotated` metadata on Pydantic request and response models through runtime validation and HTTP schema generation, retain business parameters named `self` or `cls`, and reject unbound endpoint receivers instead of silently dropping them. Serialize runtime-validated annotated responses without replaying their application validators, preserving schema metadata and serializers.
- Publish source-maintained README and roadmap pages using links pinned to the generated source commit.
- Redact application-raised `TimeoutError` as a stable 500 response instead of misclassifying it as a request timeout.
- Remove the redundant homepage supporting figure while preserving all original diagram assets and other consumers.
- Replace the quote-form demo with a browser-local preview of Summonpot's shipped bound-operation contract: `FromRequest`, bounded `AgentChoice`, and an exactly-once required operation.
- Replaced the crowded Summonpot hero and social artwork with a minimal lockup built from the existing compact mark.
- Restore the native homepage footer navigation to the Quick start guide.
- Show ModePot, repository, community, and creator links in Summonpot headers and compact menus.
- Standardized the README hero to 600px and added a visible link to the ModePot family.
- The README now links directly to Summonpot's live quick start, playground, and architecture docs.
- The README prominently links to the project website beside the ModePot family link.
- The product homepage and architecture guide now include the existing execution-flow and authority-boundary diagrams, with captions, accessible descriptions, and full-size links.

### Fixed

- Render PEP 604 unions (`int | None`) correctly on Python 3.14+ without recursing into `__origin__`. Add Python 3.14 to CI matrix and Trove classifiers. ([#76](https://github.com/tugrulguner/summonpot/issues/76))
- Add a canonical ModePot return link and correct the quick-start example URL.
- Application operation failures are now classified as redacted server errors across direct, enforced-agent, and legacy callable execution, regardless of exception type. Genuine runtime deadlines and provider/usage failures retain their HTTP classifications.
- Astro 7 and Starlight 0.42 now resolve the custom header’s components through package exports. The playground reads its example from the repository root during prerendering, and the generated Starlight 404 page is no longer shadowed by a static public file.
- Capture pageviews on the standalone website playground using the shared PostHog configuration, without duplicate initialization.
- Complete browser playground attempts with a bounded execution failure when result presentation throws, and keep retries usable without exposing exception details.
- Fix inconsistent site-wide light and dark themes, unreadable header controls, and embedded playground theme synchronization.
- Fixed empty structured data and improved the documentation site's search and AI-agent discovery metadata.
- Install Chromium and its system dependencies before the production website build so browser playground regressions can run during deployment.
- Make horizontally scrollable homepage code blocks keyboard-reachable and visibly focused.
- Prevent private URL and acquisition data from reaching website analytics through a shared SDK envelope sanitizer and conservative capture configuration, verified with decoded intercepted SDK requests.
- The packaging-consumer type check now pins Pyright to the version resolved in `uv.lock`.


## [0.9.0] - 2026-09-25

### Changed

- Reject explicit capability contracts at registration unless the current runtime can enforce their bindings, output, ordering, and call bounds; bare callable dependencies retain legacy behavior.

### Fixed

- Align raw Runtime.call mapping validation with generated HTTP input semantics for required fields, defaults, aliases, scalar declarations, canonical typed values, custom-initialized and recursive request models, nested values, and parameterless endpoints without rerunning request validators or custom initializers or invoking lossy value hooks. Preserve nested model fields in hook-free agent prompt projections, omit fields declared with `Field(exclude=True)` while retaining authoritative typed values and empty aliases, and safely fall back for hashed containers whose projected members are unhashable. Raw custom-initialized request graphs now reject model instances in exact built-in dictionary keys or values and fail closed for non-exact or otherwise uninspectable container-like values, as well as deep graphs beyond the safe inspection limit, before application constructors or container hooks can run.
- Reject ambiguous validation and serialization namespaces for every endpoint response and declared operation output at registration, and reject alias-shadowing extras from model instances or raw mappings without lossy serialization.
- Validate injected request values strictly against receiving operation parameter constraints before application code starts, including recursively resolved quoted annotations and typed Pydantic extras. The hook-free receiver vocabulary now rejects non-finite bare Decimals, Decimal `allow_inf_nan=True`, callable discriminators, string patterns, unsupported float `multiple_of`, enum contracts, and Pydantic models with custom constructors or post-init hooks at registration while retaining finite Decimal values, integer and finite Decimal `multiple_of`, ordinary safe unions and tagged unions, non-pattern string constraints, and ordinary Pydantic models.


## [0.8.0] - 2026-09-11

### Added

- Every generated route now carries an explicit OpenAPI `operationId` derived from the declared endpoint name and HTTP method, instead of FastAPI deriving one from the internal `handle` factory. Distinct paths that sanitise alike -- `/user-profile` and `/user_profile` -- no longer collide on a single id, and a name/method collision is rejected at registration with a message naming both endpoints rather than surfacing as a duplicate-operation warning in the schema. The metadata captured at registration is authoritative: `build_app()` serves ids from the plan compiled then, so later edits to a registered `EndpointDef` do not reach the schema. A definition that never went through registration is still validated when the app is built, and is rejected if its id is not the one its name and method derive. ([#79](https://github.com/tugrulguner/summonpot/issues/79))

### Changed

- `Exactly`, `AtLeast`, `AtMost` and `Between` now reject a bound that is not a built-in `int`, raising `TypeError` when the declaration is constructed rather than accepting it or failing later on a comparison. `bool` is rejected too, despite being an `int` subclass, so `Exactly(True)` no longer silently becomes `Exactly(1)`. An explicitly written `None` maximum is rejected as well -- `AtMost(None)` and `Between(1, None)` name a maximum and name it wrongly, where an omitted maximum still means unbounded, so `CallBounds(minimum=1)` and `AtLeast(1)` are unchanged. Negative and unsatisfiable integer ranges keep raising `ValueError`, and zero bounds such as `Exactly(0)` and `AtMost(0)` remain constructible. The rejection names the offending field and the rule only -- never the value it was given, and never its type -- so a declaration holding a credential cannot copy it into startup logs, and a value whose `__repr__` or type name raises still gets the documented `TypeError`. ([#92](https://github.com/tugrulguner/summonpot/issues/92))
- Prioritize enforce-or-reject contracts and input/output hardening in the roadmap; require failure semantics with result chains before broader execution and database adapters. Add a research-informed agent/context track for budgeted working context, scoped tool discovery and memory, bounded delegation, and evaluation gates while preserving body-free endpoint contracts.

### Fixed

- Correct execution-boundary documentation to distinguish one permitted operation start per request from exactly-once completion, describe direct and agent-backed endpoint paths without assuming a model, accept no-model bug reports, and keep contributor-only guidance out of distributions.
- Prevent HTTP request transport from invoking application-defined copy hooks after validation, so operations receive the exact validated value graph. Public compatibility views no longer alias that graph, and a consumed transport cannot be replayed through request defaults. Compatibility views and the runtime prompt use detached inert built-in projections, without invoking declared serializers or string/representation hooks. Unsupported values, cycles, excessive nesting, and non-finite floats use an inert placeholder; non-string mapping keys are omitted. Safe exact native UUID, date/time, timedelta, Decimal, and bytes values remain usable in prompts and typed compatibility views without application hooks. Tuple, set, and frozenset query values also retain their native kind in typed views and their contents in JSON-safe prompts. Canonical bound values are unchanged.


## [0.7.0] - 2026-09-05

### Added

- Ship the PEP 561 `py.typed` marker in the wheel and source distribution, so type checkers honour summonpot's inline annotations for an installed package rather than only for a source checkout. CI now verifies the marker in both artifacts and type-checks a small consumer against the installed wheel. ([#77](https://github.com/tugrulguner/summonpot/issues/77))
- Path placeholders in a route now bind from the URL on body-carrying methods (`POST`, `PUT`, `PATCH`), not just on bodyless ones. A `{name}` placeholder must match exactly one required scalar parameter; that parameter is exposed as an OpenAPI path parameter and excluded from the generated request body model, so the URL is the single authority for it and a conflicting body field can no longer win. A placeholder with no matching parameter, a repeated placeholder, an optional path parameter, or a non-scalar one now fails at import time. When the URL owns every declared parameter the route now carries no request body at all, so it is callable with nothing but its path segments. A path parameter may itself be called `body`: the synthetic request-body parameter steps aside rather than colliding with it, so a route such as `/items/{body}` builds instead of failing application startup. Placeholders are matched exactly as written and are no longer stripped, so a non-canonical spelling like `/items/{ item_id }` is rejected as the malformed declaration it is rather than silently registering under a name the served route does not use. ([#78](https://github.com/tugrulguner/summonpot/issues/78))
- Execute one fully resolved required `Exactly(1)` operation directly when the endpoint uses a Pydantic request model, it has at least one validated-request binding, uses only validated request values or immutable identity-stable callable defaults, and its output exactly matches the endpoint response model, without resolving or constructing a provider model.
- Runtime-enforced bound operations with trusted request injection, model-visible choices, one permitted start per request, and locally validated output.

### Changed

- `Runtime(retries=...)` now validates its argument during construction instead of storing it unchecked. A float or string previously survived construction and endpoint registration, then failed on the first HTTP request as `AttributeError: 'float' object has no attribute 'copy'` from inside agent construction, which the server returned as an unexplained 500; negative and boolean values reached successful requests while meaning nothing. Non-integers now raise `TypeError` and negative integers `ValueError`, both naming `retries` and the accepted range. The `TypeError` names only the offending type, never the value it was given, so a configuration value holding a credential is not copied into startup logs and a value whose `__repr__` raises still gets the documented error; a negative integer still reports its count. `bool` is rejected despite being an `int` subclass. `retries=0`, `retries=1` and the default are unchanged. ([#93](https://github.com/tugrulguner/summonpot/issues/93))
- Add structured contributor onboarding with issue-backed or generated orphan changelog fragments.
- Clarified the README with separate deterministic and agentic endpoint declarations in one code example, aligned the visual diagram with those two paths, and used agent-oriented language for agentic ownership and decisions.
- Clarify that summonpot modernizes APIs through simple contract-based endpoints that combine deterministic operations with bounded agentic decisions.
- Declare the tested Python support range as 3.11–3.13 so installers do not select Summonpot on Python 3.14 before its annotation compatibility work lands.
- README presentation now leads with one declaration for deterministic operations and agentic decisions, with a runnable bound-authority quick start and execution diagram.
- Replaced the text-heavy endpoint formula with a rendered PNG diagram and showed deterministic application work and agentic choice explicitly in one endpoint code example.
- Resequence the roadmap around the researched single-operation deterministic walking skeleton before multi-operation result chains, broader authority sources, and database adapters.
- Restored the established README, removed version-specific release and migration prose, strengthened the introduction around deterministic application operations and agentic decisions sharing one endpoint declaration, and added the permanent ModePot Discord community links.

### Fixed

- Reject malformed managed-block markers in `summonpot add skills` instead of silently appending a second block to shared instruction files (`AGENTS.md`, `.github/copilot-instructions.md`). ([#80](https://github.com/tugrulguner/summonpot/issues/80))
- Close direct-execution serializer and mutable-default trust gaps; preserve scalar endpoint defaults and document the Pydantic request-model requirement. Revalidate output from its declared schema without invoking serializers, preserving canonical aliases and `Any` payloads. Validate colliding extra fields separately so they cannot overwrite declared fields, while retaining valid extras. Require Pydantic >=2.13.5,<2.14 and pydantic-core >=2.46.5,<2.47 for the tested version-sensitive validator integration; older Pydantic installations must upgrade. Correct the root contributor guidance to describe the shipped direct path. Reject custom model initializers in runtime-enforced output schemas at registration instead of allowing a nested-validation bypass. Preserve a plan-bound validated HTTP request snapshot so validation aliases remain valid and request validators do not run twice.
- Corrected the installed coding-agent skill and contributor guidance to describe Summonpot's AI API modernization position, supported request declarations, runtime extras, safe network exposure, and the narrow shipped direct-execution boundary while keeping unsupported declarations agent-backed. The contributor-file changes do not alter the installed API or require a user migration.
- Read and write files as UTF-8 instead of the locale encoding. On Windows, where `locale.getpreferredencoding()` is cp1252, `summonpot add skills` decoded the packaged skill as cp1252 and held mojibake in memory, and a locale that cannot represent the skill's characters at all — ASCII, as a POSIX `LC_ALL=C` child reports — failed the write outright. Every `Path.read_text()` and `Path.write_text()` call now passes `encoding="utf-8"` explicitly, which also makes the tests portable across locales.

  Updating the managed block in a shared file no longer rewrites the line endings of the content around it. Both sides of that read-modify-write used universal-newline translation, which folded every `\r\n` to `\n` on read and expanded every `\n` to `os.linesep` on write, so a command scoped to one fenced region produced a whole-file diff: CRLF to LF on macOS and Linux, LF to CRLF on Windows. The file is now read and written with translation off, and the managed block itself is written with whatever line ending the file already uses.


## [0.6.0] - 2026-08-24

### Upgrading from 0.5.0

The application API is now `Summon`, the CLI loads a module-level variable named
`summon`, and the application instance is the endpoint decorator:

```python
from pydantic import BaseModel
from summonpot import Summon


class Request(BaseModel):
    query: str


class Response(BaseModel):
    answer: str


summon = Summon("service")


@summon("/route")
def route(request: Request) -> Response:
    """Answer the query."""
    ...
```

Replace `from summonpot import Pot`, `pot = Pot(...)`, and `@pot.summon(...)` together.
The package-root `Pot` export and `summonpot.pot` module are removed.
`Summon.summon(...)` remains a temporary source-compatibility alias after constructing a
`Summon`, but new code should use the application instance directly.

### Changed

- Use ellipsis for complete endpoint declaration bodies and reject direct Python calls to registered declarations. ([#67](https://github.com/tugrulguner/summonpot/pull/67))
- Replace the `Pot` application object and `@pot.summon(...)` syntax with `Summon`, a module-level `summon` variable, and direct `@summon(...)`; `Summon.summon(...)` remains a temporary source-compatibility alias. ([#68](https://github.com/tugrulguner/summonpot/pull/68))

### Fixed

- Update the bundled coding-agent skill for typed operation bindings, registration validation, and the current runtime execution boundary. ([#66](https://github.com/tugrulguner/summonpot/pull/66))


## [0.5.0] - 2026-08-23

### Added

- Add `Operation`, argument sources (`FromRequest`, `FromResult`, `FromContext`, `AgentChoice`), and call bounds, so an endpoint can declare where each operation argument comes from. `Depends` and `Required` now accept a contract as well as a callable. ([#60](https://github.com/tugrulguner/summonpot/pull/60))
- Validate capability contracts when an endpoint is declared: bindings must name real arguments and request fields, an operation that declares `bind` must bind every argument, `FromResult` must name a declared operation with a validatable output field, and the operations must be orderable. ([#61](https://github.com/tugrulguner/summonpot/pull/61))
- Reject a binding whose declared type provably cannot satisfy the argument it feeds, and require `AgentChoice(from_result=...)` to name a collection the model can select an item from. ([#63](https://github.com/tugrulguner/summonpot/pull/63))

### Changed

- Added AGENTS.md and internal review skills for contributors, and recorded the shipped coding-agent skills in the roadmap foundation. ([#57](https://github.com/tugrulguner/summonpot/pull/57))
- Split agent guidance into a root AGENTS.md and a nested src/summonpot/AGENTS.md, added a CLAUDE.md symlink, and kept AGENTS.md out of the installed wheel. ([#58](https://github.com/tugrulguner/summonpot/pull/58))

### Fixed

- Capability parameters now carry their resolved annotation alongside the display string, so `ToolDef.parameters` no longer reports a type it does not expose. ([#62](https://github.com/tugrulguner/summonpot/pull/62))
- Align package metadata, CLI help, OpenAPI, the README, and the roadmap with Summonpot's contract-first positioning and shipped registration-time operation validation. ([#64](https://github.com/tugrulguner/summonpot/pull/64))


## [0.4.0] - 2026-08-17

### Added

- Add `summonpot add skills`, which installs a summonpot skill into Claude Code, Cursor, Windsurf, Copilot, Cline, or Codex so a coding agent knows the endpoint contract. ([#45](https://github.com/tugrulguner/summonpot/pull/45))

### Changed

- Aligned README, CLI, OpenAPI, roadmap, and package metadata with the shipped provider-neutral agent runtime while clearly labeling deterministic endpoint execution as planned. ([#44](https://github.com/tugrulguner/summonpot/pull/44))
- Redesigned the README around the executable endpoint contract with a faster quick start, clearer shipped-versus-planned boundaries, an execution diagram, example progression, and contributor and project-support entry points. ([#46](https://github.com/tugrulguner/summonpot/pull/46))
- Clarified the public positioning from signature-first to contract-first: typed endpoint declarations become executable APIs. ([#47](https://github.com/tugrulguner/summonpot/pull/47))


## [0.3.0] - 2026-08-15

### Upgrading from 0.2.0

This release turns a number of silently-wrong declarations into errors. Most surface
the moment a pot is imported, so an upgrade either starts cleanly or tells you exactly
what to change.

Registration now fails for an endpoint that:

- has no docstring — the docstring is the endpoint's goal, so it cannot be empty;
- has a path without a leading slash;
- reuses a `(path, method)` pair already registered;
- passes `stream=True`, which was never implemented;
- has an annotation that cannot be resolved, such as a `TYPE_CHECKING`-only import or
  a model defined inside a function;
- declares a capability that is an unbound method or is not callable;
- uses a bodyless method (`GET`, `DELETE`, `HEAD`) with a Pydantic request model, an
  unsupported HTTP verb, or a parameter with no query encoding such as a mapping.

Two changes alter behaviour rather than rejecting it:

- **`method=` is now honoured.** An endpoint that declared `method="GET"` previously
  served `POST`; it now serves `GET`, and its parameters move to the query string.
  Clients of such an endpoint need updating.
- **Request validation is stricter.** A generic such as `list[int]` now validates its
  element types instead of accepting anything, so requests that were wrongly accepted
  may now return 422. Optional parameters accept an explicit `null`, which they
  previously rejected.

One change surfaces under traffic rather than at import, and is the one worth checking
before deploying:

- **Synchronous capabilities now run in a worker thread** so a slow operation no longer
  blocks concurrent requests. A capability that captures a thread-affine resource — a
  default SQLite connection is the common case — will now fail at request time. Give
  such capabilities their own connection per call.

Finally, endpoint failures now return meaningful status codes (`429`, `502`, `504`)
rather than an opaque `500`, and the response body no longer carries model output or
provider text. Anything depending on the previous bodies should read the status instead.

### Added

- Add `usage_limits` and `timeout` to `Runtime`, and re-export `UsageLimits`, so a single endpoint call can be capped on requests, tokens, cost, and wall-clock time. ([#23](https://github.com/tugrulguner/summonpot/pull/23))
- Add `Pot(model=...)` and `Pot(runtime=...)`, and resolve `SUMMONPOT_MODEL` at call time so setting it after import still applies. ([#33](https://github.com/tugrulguner/summonpot/pull/33))
- Honour `method=` on `@pot.summon`, registering the declared HTTP verb and taking parameters as a query string for methods that carry no body. ([#38](https://github.com/tugrulguner/summonpot/pull/38))
- Added progressive, executable examples covering typed endpoints, required deterministic capabilities, bounded agentic choices, HTTP methods, runtime limits, provider selection, and multi-file services. ([#41](https://github.com/tugrulguner/summonpot/pull/41))

### Changed

- Move the shared annotation helpers into a single module so endpoint and capability inspection can no longer drift apart. ([#26](https://github.com/tugrulguner/summonpot/pull/26))
- Raise the CI coverage floor from 50% to 85%, close to the project's actual 88%, so a real regression fails the build. ([#34](https://github.com/tugrulguner/summonpot/pull/34))
- Document that `serve()` binds every interface by default, that endpoints carry no authentication yet, and how to bound and protect an exposed pot. ([#35](https://github.com/tugrulguner/summonpot/pull/35))
- Document that the closed capability set governs which operations run, not the arguments they receive, and that each capability must validate its own inputs. ([#36](https://github.com/tugrulguner/summonpot/pull/36))
- Reuse an endpoint's agent across requests by moving required-capability tracking onto per-run state, instead of rebuilding every tool and output schema on each call. ([#37](https://github.com/tugrulguner/summonpot/pull/37))

### Fixed

- Load pot files that define dataclasses by registering the module in `sys.modules` before executing it. ([#17](https://github.com/tugrulguner/summonpot/pull/17))
- Report an unloadable pot file once, instead of following it with the exit code formatted as a second error. ([#18](https://github.com/tugrulguner/summonpot/pull/18))
- Append the pot file's directory to `sys.path` instead of prepending it, so a neighbouring module can no longer shadow the standard library. ([#19](https://github.com/tugrulguner/summonpot/pull/19))
- Run synchronous capabilities in a worker thread so a slow operation no longer blocks concurrent requests, and await callable objects whose `__call__` is async. ([#20](https://github.com/tugrulguner/summonpot/pull/20))
- Accept `functools.partial` and callable objects as capabilities, so an operation can carry a connection or configuration, and raise a clear error for values that are not callable. ([#21](https://github.com/tugrulguner/summonpot/pull/21))
- Reject an unbound method used as a capability at registration, instead of hiding `self` from the declared parameters while still demanding it in the schema sent to the model. ([#22](https://github.com/tugrulguner/summonpot/pull/22))
- Generate request schemas from the resolved annotation, so optional parameters accept null, `Any` accepts any JSON value, and generics validate their element types. ([#24](https://github.com/tugrulguner/summonpot/pull/24))
- Return meaningful status codes when an endpoint exceeds its budget, times out, or the model fails to satisfy the contract, instead of an opaque 500. ([#25](https://github.com/tugrulguner/summonpot/pull/25))
- Raise at registration when an endpoint annotation cannot be resolved, instead of silently degrading the endpoint to an untyped request body and response. ([#27](https://github.com/tugrulguner/summonpot/pull/27))
- Reject an endpoint without a docstring at registration, instead of running it with an empty agent instruction. ([#28](https://github.com/tugrulguner/summonpot/pull/28))
- Reject an endpoint path that does not start with '/' at registration, instead of building a route no request can reach. ([#29](https://github.com/tugrulguner/summonpot/pull/29))
- Reject a second endpoint registered on an existing path, instead of silently making it unreachable while documenting it in place of the first. ([#30](https://github.com/tugrulguner/summonpot/pull/30))
- Raise when an endpoint is declared with `stream=True`, instead of accepting the flag and returning a fully buffered response. ([#31](https://github.com/tugrulguner/summonpot/pull/31))
- Copy pot-level capabilities per endpoint so marking one `Required` cannot make it required for every other endpoint that declares it. ([#32](https://github.com/tugrulguner/summonpot/pull/32))
- Allow `SUMMONPOT_MODEL=test` to use pydantic-ai's built-in keyless model, so summonpot can be tried without a provider account. ([#39](https://github.com/tugrulguner/summonpot/pull/39))
- Report a missing or invalid provider configuration as a labelled error with the cause in the server log, instead of an opaque 500. ([#40](https://github.com/tugrulguner/summonpot/pull/40))


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
