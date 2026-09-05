# summonpot

<p align="center">
  <img src="summonpot.png" alt="Summonpot" width="600">
</p>

<p align="center">
  <strong>Declare deterministic operations and agentic decisions through one framework.</strong>
</p>

<p align="center">
  A contract-first Python framework for combining application-owned execution and agent-owned choices in one typed HTTP API, with simple, fully contract-based endpoints.
</p>

<p align="center">
  <a href="https://github.com/tugrulguner/summonpot/actions/workflows/ci.yml"><img src="https://github.com/tugrulguner/summonpot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/summonpot/"><img src="https://img.shields.io/pypi/v/summonpot" alt="PyPI version"></a>
  <a href="https://pypi.org/project/summonpot/"><img src="https://img.shields.io/pypi/pyversions/summonpot" alt="Python versions"></a>
  <a href="https://github.com/tugrulguner/summonpot/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://discord.gg/u3AANZr6RG"><img src="https://img.shields.io/badge/Discord-Join%20ModePot-5865F2?logo=discord&amp;logoColor=white" alt="Join the ModePot Discord"></a>
  <a href="https://github.com/tugrulguner/summonpot"><img src="https://img.shields.io/github/stars/tugrulguner/summonpot?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-summonpot">Why summonpot</a> ·
  <a href="#exact-capabilities-not-ambient-authority">Capabilities</a> ·
  <a href="#how-it-works-today">How it works</a> ·
  <a href="#examples">Examples</a> ·
  <a href="#community">Community</a> ·
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/tugrulguner/summonpot/a3238041b53f6f07d4575ecfae5a77f60a551500/docs/assets/one-declaration-two-flows.png" alt="One Summonpot application branches into the exact shipped single-operation direct slice or an agent-backed endpoint through the same typed HTTP and OpenAPI framework" width="960">
</p>

Summonpot modernizes APIs for AI without replacing the endpoint with a separate agent
layer. The endpoint remains the stable public abstraction while its contract combines exact
application behavior with explicitly bounded agentic decisions.

The ellipsis is declaration syntax, not an unfinished implementation. The signature,
docstring, operations, argument bindings, and return type are the executable contract.
`Depends(...)` and `Required(...)` attach deterministic application code. `AgentChoice()`
marks the exact arguments where the agent may decide. Deterministic and agentic endpoints
use the same declaration style, request/response validation, routing, and OpenAPI instead of
separate API and agent frameworks. Summonpot owns the bounded agent loop, operation
enforcement, and structured output. Calling a registered declaration directly raises a
clear error; serve the application or invoke its generated HTTP route instead.

> [!IMPORTANT]
> One fully resolved `Exactly(1)` operation path now executes directly without resolving
> or constructing a model. All other declarations still use Summonpot's provider-neutral
> agent runtime. Within the runtime-enforced binding slice, the agent controls only explicit
> `AgentChoice()` arguments; unsupported legacy binding shapes may remain model-supplied.
> Broader multi-operation deterministic execution remains on the
> [roadmap](ROADMAP.md), not shipped behavior.

## Why summonpot?

A conventional API puts deterministic work in a handler. An agent-first stack starts from
an agent workflow and then wraps it in HTTP. Summonpot declares both through the same
contract-first framework, so applications keep one public API as the balance changes
between exact operations and semantic decisions:

The following conceptual declaration omits the application-specific models and service
implementation; the [quick start](#quick-start) is the standalone example.

```python
from typing import Literal

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon


summon = Summon("research-api")


def build_deterministic_report(topic: str) -> ResearchResponse:
    """Run the application's fully resolved research operation."""
    return research_service.build_response(topic=topic, format="detailed")


deterministic_report_operation = Operation(
    build_deterministic_report,
    bind={"topic": FromRequest("topic")},
    output=ResearchResponse,
)


def build_agentic_report(
    topic: str,
    format: Literal["summary", "detailed"],
) -> ResearchReport:
    """Run the exact operation with one declared semantic choice."""
    return research_service.build(topic=topic, format=format)


agentic_report_operation = Operation(
    build_agentic_report,
    bind={
        "topic": FromRequest("topic"),
        "format": AgentChoice(),
    },
    output=ResearchReport,
)


@summon("/reports/deterministic")
def deterministic_report(
    request: ResearchRequest,
    report=Required(deterministic_report_operation, calls=Exactly(1)),
) -> ResearchResponse:
    """Return the detailed report through a fully resolved operation path."""
    ...


@summon("/reports/agentic")
def agentic_report(
    request: ResearchRequest,
    report=Required(agentic_report_operation, calls=Exactly(1)),
) -> ResearchResponse:
    """Choose the report format and return the sourced report."""
    ...
```

Those declarations answer the questions an API framework needs to answer:

| Question | Declared by |
|---|---|
| What may the caller send? | `ResearchRequest` |
| What must the endpoint achieve? | The docstring |
| What application authority may execution use? | `Depends(...)` and `Required(...)` |
| Which inputs must come from trusted application data? | `FromRequest(...)` and other bindings |
| Where may the agent make a semantic choice? | Explicit `AgentChoice(...)` bindings |
| What may the endpoint return? | `ResearchResponse` |
| Where is orchestration code? | Owned by summonpot |

The request carries business data only. The endpoint goal is fixed in code. Exact
operations remain application-owned, while the agent can choose only within the authority
declared for that endpoint. A response is not accepted until every `Required(...)`
operation has completed successfully.

| | Conventional APIs | Agent-first stacks | summonpot |
|---|---|---|---|
| Mental model | Write a handler | Configure an agent | Declare one endpoint |
| Deterministic work | Handler code | Usually exposed as tools | Exact application-owned operations |
| Agentic decisions | Separate agent workflow | Primary abstraction | Explicit choices in the same declaration |
| HTTP | Built around the handler | Added around the agent | Generated from the declaration |
| Application authority | Held by handler code | Often assembled separately | Closed by the endpoint contract |
| Final output | Handler convention | Provider or framework convention | Locally validated response model |

### One declaration style, both endpoint flows

`/reports/deterministic` binds every operation argument to validated application data; its
operation output is exactly the endpoint response model, so the fully resolved endpoint
executes once without constructing a model. `/reports/agentic` uses the same declaration
style but adds one explicit `AgentChoice()`. The endpoint with `AgentChoice()` still uses
the agent runtime. Both keep typed request/response contracts, operation enforcement,
routing, and OpenAPI under Summonpot.

## What ships today

- **One declaration style for deterministic operations and agentic decisions**, sharing the same
  request, response, route, validation, and OpenAPI contract.
- **Contract-first endpoints** with a required goal and typed request/response contracts.
- **Closed capability sets** made from exact application-owned callables.
- **Optional and mandatory operations** through `Depends(...)` and `Required(...)`.
- **Runtime-enforced required use**, tracked per request rather than trusted to a prompt.
- **Bound exactly-once operations** for the first complete runtime slice: trusted
  `FromRequest` values and callable defaults are removed from the operation tool schema,
  direct `AgentChoice` arguments remain visible, one start is permitted, and `output=` is
  locally validated before success.
- **Single-operation deterministic execution** when one required `Exactly(1)` operation
  uses a Pydantic request model and has at least one `FromRequest` binding; every remaining argument comes from `FromRequest`
  or an immutable identity-stable callable default, and its output is exactly the endpoint
  response model. This path does not resolve, construct, or call a model.
- **Typed `Operation` contracts** that declare request, prior-result, context, or
  agent-chosen argument sources without expanding the endpoint API.
- **Registration-time contract validation** that rejects missing sources, invalid result
  references, unsupported choices, and provably incompatible types before serving.
- **Provider-neutral model selection** for OpenAI, Anthropic, Google, Groq, Mistral,
  OpenRouter, and xAI.
- **Generated HTTP and OpenAPI contracts** for body and query endpoints.
- **GET, POST, PUT, PATCH, DELETE, and HEAD routes**, keyed by `(path, method)`.
- **Local response validation**, bounded retries, usage limits, timeouts, and redacted
  public failures.
- **A keyless test model** for exercising routes and schemas before adding provider
  credentials.
- **Coding-agent skills** for Claude Code, Cursor, Windsurf, GitHub Copilot, Cline, and
  OpenAI Codex, including typed operation bindings and their current runtime boundary.

## Quick start

### 1. Install

```bash
pip install "summonpot[serve,cli]"
```

This source revision requires Pydantic `>=2.13.5,<2.14` and pydantic-core
`>=2.46.5,<2.47`. Earlier Pydantic versions are no longer supported. Output
revalidation uses a version-sensitive core option to avoid reusing validators that
trust existing model instances; the dependency bounds keep that integration on the
tested minor versions. These requirements apply to newly built artifacts, not to
already-published packages.

Start without a provider account by selecting the built-in test model:

```bash
export SUMMONPOT_MODEL=test
```

The test model is keyless, not side-effect-free. An endpoint with capabilities may call
them using generated placeholder arguments. Use harmless capabilities when testing
wiring; do not attach destructive operations or treat the model as a dry-run sandbox.

### 2. Declare an endpoint

Create `app.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field
from summonpot import Summon


class ReviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)


class ReviewResponse(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]
    summary: str


summon = Summon("review-api")


@summon("/review")
def review(request: ReviewRequest) -> ReviewResponse:
    """Classify the text's sentiment and summarize it in one short sentence."""
    ...
```

The ellipsis marks a complete endpoint declaration. Summonpot never calls that body, and
direct Python calls are rejected at the decorator boundary.

### 3. Serve it

```bash
summonpot serve app.py --host 127.0.0.1 --port 8000
```

Open the generated API documentation at
[`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs), or call the endpoint directly:

```bash
curl -X POST http://127.0.0.1:8000/review \
  -H 'Content-Type: application/json' \
  -d '{"text":"The endpoint contract is surprisingly small."}'
```

The test model returns schema-valid placeholder data. To receive a real agent-generated
answer, install a provider extra and select a provider-qualified model:

```bash
pip install "summonpot[serve,cli,anthropic]"
export SUMMONPOT_MODEL=anthropic:claude-sonnet-4-5
export ANTHROPIC_API_KEY='<your key>'
```

The endpoint code and HTTP contract do not change when the provider changes.

## Exact capabilities, not ambient authority

A capability is ordinary application code. It runs for real; summonpot never replaces
its implementation.

```python
def calculate_quote(
    unit_price_cents: int,
    quantity: int,
    tax_rate_percent: str,
) -> dict[str, int]:
    """Calculate an exact quote using the service's approved pricing rules."""
    return pricing_service.calculate(
        unit_price_cents=unit_price_cents,
        quantity=quantity,
        tax_rate_percent=tax_rate_percent,
    )
```

Attach it to one endpoint, continuing from the application and models defined above:

```python
from summonpot import Required


@summon("/quotes")
def create_quote(
    request: QuoteRequest,
    calculation=Required(calculate_quote),
) -> QuoteResponse:
    """Calculate and return the exact approved quote."""
    ...
```

| Declaration | Runtime contract |
|---|---|
| `Depends(operation)` | The operation is available to the endpoint and may be called. |
| `Required(operation)` | Final output is rejected until the operation succeeds. |

For bare callables and broader operation graphs, `Required(...)` proves only that the
operation returned successfully at least once during that request. The narrow bound form
shown below additionally enforces trusted request injection, local operation-output
validation, and `Exactly(1)`. Ordering, idempotency, and provenance-backed final claims
remain separate concerns.

Capabilities do not become request-body fields or OpenAPI parameters. Their docstrings
and annotations define the tool schema visible to the agent, while their implementations
define the real application behavior.

The capability set is closed. For one required typed operation with `Exactly(1)`, the
runtime injects `FromRequest` values, removes them and callable defaults from any
model-visible tool schema, validates the declared operation output, and rejects a second
start. If the endpoint uses a Pydantic request model, has at least one `FromRequest`
binding, uses only `FromRequest` or supported immutable callable defaults, and that output
is exactly the endpoint response model,
Summonpot executes the operation directly. Otherwise direct `AgentChoice` arguments remain
visible to the agent. Request values on agentic paths still appear in the agent's user
message; tool-schema hiding is not prompt secrecy. Other operation shapes remain on the
legacy agent-supplied path until their execution semantics ship. Every operation must still
enforce authorization.
Pass exact operations, never raw database sessions, engines, connections, cursors,
arbitrary SQL, shell access, or ambient filesystem authority.

See the complete executable
[`Required(...)` quote example](examples/02_required_capability.py).

## Typed operation contracts fail before serving

Use `Operation` when a capability's dataflow is part of the endpoint contract rather
than something the agent should invent:

```python
from my_service.models import Customer, CustomerRequest, CustomerResponse
from my_service.operations import load_customer
from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon


summon = Summon("customer-api")

customer_from_request = Operation(
    load_customer,
    bind={
        "customer_id": FromRequest("customer_id"),
        "format": AgentChoice(),
    },
    output=Customer,
)


@summon("/customers")
def get_customer(
    request: CustomerRequest,
    customer=Required(customer_from_request, calls=Exactly(1)),
) -> CustomerResponse:
    """Load this customer and return the approved customer view."""
    ...
```

The contract is immutable after construction. At registration, summonpot verifies that:

- every required operation argument has an explicit source;
- `FromRequest(...)` names a real request field;
- `FromResult(...)` names a declared producer and a readable, typed output field;
- `AgentChoice(...)` selects from a supported collection and fits its receiving argument;
- known source, element, and destination types are compatible; and
- ordering references name operations declared by the same endpoint.

The rule is deliberately conservative: a declaration is rejected only when its
incompatibility is provable. Missing annotations, `Any`, framework context, and type
relationships the checker cannot establish remain unknown rather than becoming false
registration errors. An annotation that names a type Python cannot resolve is still an
invalid endpoint declaration and fails at import.

For example, binding an `int` request field to a `str` operation argument fails while the
module is imported. A `Customer` value may feed a `Person` argument when `Customer` is a
subclass, and Python's numeric widening permits `int` or `bool` to feed `float`.

> [!IMPORTANT]
> Registration validates and stores every binding source. Runtime enforcement covers one
> required `Exactly(1)` operation using `FromRequest`, direct `AgentChoice`, and callable
> defaults. When every required value is application-owned and the operation output exactly
> matches the endpoint response model, that operation executes without a model. `FromResult`,
> `FromContext`, `after`, broader call bounds, and multi-operation direct paths remain
> planned; unsupported shapes keep their existing agent-supplied argument behavior.

## How it works today

```text
HTTP request
    |
    v
Pydantic request validation + OpenAPI contract
    |
    v
Runtime.call(...)
    |
    +---- one fully resolved Exactly(1) operation
    |          |
    |          +---- execute directly; validate declared output
    |
    +---- otherwise: configured provider-neutral model
               |
               +---- may call only declared capabilities
               |
               +---- Required-operation gate
    |
    v
Local Pydantic response validation
    |
    v
HTTP response
```

The endpoint docstring becomes the fixed goal. Request data becomes the user message.
Capabilities become the complete set of callable operations. The response model becomes
both the structured-output schema and the final local validator.

Pydantic AI is an internal runtime dependency. Applications use `Summon`, `@summon`,
Pydantic models, and declarative capabilities; they do not construct provider clients or
Pydantic AI agents.

### The contract stays stable across execution paths

Summonpot chooses its current execution path without adding a second endpoint API:

| Contract state | Current execution |
|---|---|
| Pydantic request model, one required `Exactly(1)` operation, at least one `FromRequest` binding, only `FromRequest` or immutable identity-stable defaults, exact response-model output | Execute directly without a model |
| A bounded semantic choice remains | Use the agent runtime with declared capabilities |
| Unsupported or broader operation graph | Keep the existing agent path until its full semantics ship |

Broader graph execution and ordering, multi-operation deterministic execution,
SQLAlchemy/SQLite operation adapters, write receipts, streaming, and built-in
authentication are **planned, not shipped**. See
[ROADMAP.md](ROADMAP.md) for the design boundaries and implementation order.


Supported immutable callable defaults are exact built-in `None`, `bool`, `int`,
`float`, `complex`, `str`, and `bytes` values, plus tuples and frozensets containing
only those values recursively. Custom types (including subclasses of those built-ins)
and mutable defaults keep the endpoint agent-backed; copy hooks are not proof of
immutability. Scalar request declarations also remain agent-backed.

## HTTP methods and OpenAPI

`POST` is the default. Body endpoints take one Pydantic request model. Bodyless methods
such as `GET`, `DELETE`, and `HEAD` declare scalar or scalar-sequence query parameters:

This fragment continues from an existing module-level `summon` application:

```python
from typing import Literal

from pydantic import BaseModel


class TicketPage(BaseModel):
    tickets: list[str]


@summon("/tickets", method="GET")
def list_tickets(
    status: Literal["open", "closed"] = "open",
    ids: list[int] | None = None,
) -> TicketPage:
    """List tickets matching the requested filters."""
    ...
```

`GET /tickets` and `POST /tickets` may coexist. Registering the same normalized
`(path, method)` twice fails at import time, as do missing docstrings, unresolved type
annotations, invalid capability callables, duplicate capability names, unsupported query
types, and `stream=True`.

### Path parameters

A `{name}` placeholder in a route binds from the URL on every method, body-carrying
ones included. Each placeholder must match exactly one **required scalar** parameter
(`str`, `int`, `float`, `bool`, `UUID`):

```python
@summon("/customers/{customer_id}", method="POST")
def update_customer(customer_id: int, name: str) -> str:
    """Update one customer."""
    ...
```

`customer_id` is documented as an OpenAPI path parameter and is **excluded from the
generated request body model**, so the value exists in exactly one place. The URL is
the only authority for it: a body that also carries `customer_id` does not override
the URL.

When the URL owns **every** declared parameter the route carries no request body at
all, so it is callable with nothing but its path segments:

```python
@summon("/items/{item_id}", method="POST")
def touch_item(item_id: int) -> Item:
    """Touch one item."""
    ...
```

```bash
curl -X POST http://localhost:8000/items/7
```

These fail at import time, next to the other registration errors above: a placeholder
with no matching parameter, the same placeholder twice, a path parameter with a
default, and a path parameter annotated with anything but a supported scalar. A
structured value belongs in the body.

## Provider and model configuration

| Provider | Install extra | Model example | API-key variable |
|---|---|---|---|
| OpenAI | `summonpot[openai]` | `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `summonpot[anthropic]` | `anthropic:claude-sonnet-4-5` | `ANTHROPIC_API_KEY` |
| Google | `summonpot[google]` | `google:gemini-2.5-flash` | `GOOGLE_API_KEY` |
| Groq | `summonpot[groq]` | `groq:llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Mistral | `summonpot[mistral]` | `mistral:mistral-large-latest` | `MISTRAL_API_KEY` |
| OpenRouter | `summonpot[openrouter]` | `openrouter:anthropic/claude-sonnet-4` | `OPENROUTER_API_KEY` |
| xAI | `summonpot[xai]` | `xai:grok-4` | `XAI_API_KEY` |

Set one default for the `Summon` application through `SUMMONPOT_MODEL` or in Python:

```python
summon = Summon("research-api", model="openrouter:anthropic/claude-sonnet-4")
```

Override it for one endpoint without changing that endpoint's HTTP contract:

```python
@summon("/research", model="anthropic:claude-sonnet-4-5")
def research(request: ResearchRequest) -> ResearchResponse:
    """Research the topic and return a sourced report."""
    ...
```

OpenRouter keeps the upstream provider and model after the first colon. Legacy
unprefixed model names resolve through OpenAI for backward compatibility.

## Bounding a call

**Binding and exposure:** A reachable endpoint can spend the operator's provider credit,
so set explicit usage limits and a timeout:

```python
from summonpot import Summon, UsageLimits
from summonpot.runtime import Runtime


summon = Summon(
    "my-service",
    runtime=Runtime(
        usage_limits=UsageLimits(
            request_limit=8,
            total_tokens_limit=40_000,
        ),
        timeout=30.0,
    ),
)
```

| HTTP status | Public meaning |
|---|---|
| `422` | Request validation failed. |
| `429` | The configured usage limit or provider rate limit was exceeded. |
| `502` | The provider failed or the agent did not satisfy the endpoint contract. |
| `504` | The endpoint exceeded its timeout. |
| `500` | Provider configuration or application capability failed. |

Provider text, agent output, and capability details stay in operator logs rather than
public error bodies.

The timeout bounds how long summonpot waits. It cannot terminate a synchronous capability
already running in a worker thread, so give irreversible or long-running operations an
internal deadline and idempotency policy of their own. Open thread-affine resources such
as default SQLite connections inside the capability call rather than capturing them
outside it.

Summonpot currently has no authentication layer. Bind local development to `127.0.0.1`.
Before exposing a service, put authentication in front of it and configure runtime limits.

## Examples

The [`examples/`](examples/) directory grows from one endpoint to a multi-file service:

| Level | Example | What it demonstrates |
|---|---|---|
| 1 | [`basic_app.py`](examples/basic_app.py) | Minimal typed request and response |
| 2 | [`02_required_capability.py`](examples/02_required_capability.py) | Required exact calculation |
| 3 | [`03_agentic_order.py`](examples/03_agentic_order.py) | Bounded choice plus a required write |
| 4 | [`04_http_methods.py`](examples/04_http_methods.py) | GET/POST routing and query parameters |
| 5 | [`05_bounded_runtime.py`](examples/05_bounded_runtime.py) | Limits, timeout, and model override |
| 6 | [`06_support_service/`](examples/06_support_service/) | Multi-file typed operation chain and persisted ticket |
| 7 | [`07_bound_operation.py`](examples/07_bound_operation.py) | Enforced `FromRequest` + `AgentChoice` with `Exactly(1)` |
| 8 | [`08_direct_execution.py`](examples/08_direct_execution.py) | Credential-free single-operation deterministic execution |

The [examples guide](examples/README.md) includes a real HTTP call for every level and
explains what runs today and what remains planned.

## Give your coding agent the contract

Summonpot uses an ellipsis as a declaration body, which is easy for a coding agent to
mistake for an unfinished handler. Install the bundled skill so the agent knows the
endpoint shape, typed operation sources, registration rules, capability boundary, HTTP
behavior, and runtime caveats:

```bash
summonpot add skills
```

With no arguments, summonpot detects agent configuration already present in the project.
Choose one explicitly when needed:

```bash
summonpot add skills --agent claude
summonpot add skills --agent cursor
summonpot add skills --agent windsurf
summonpot add skills --agent copilot
summonpot add skills --agent cline
summonpot add skills --agent codex
```

Use `--path ./myproject` to target another project directory. Shared files such as
`AGENTS.md` and `.github/copilot-instructions.md` are updated inside a managed block so
surrounding project instructions remain intact.

## Community

The [ModePot Discord](https://discord.gg/u3AANZr6RG) is the shared community for
summonpot, intpot, dexpot, and the rest of the project family. Join to discuss use cases,
ask implementation questions, and help shape declaration-first Python frameworks.

Use GitHub issues for reproducible bugs and scoped feature proposals. Use Discord for
open-ended design discussion, early ideas, and help applying the frameworks to real
projects.

## Contributing

Summonpot is early enough that a focused contribution can still shape the framework, not
just polish its edges.

Useful places to contribute include:

- executable examples for real application workflows;
- provider and HTTP acceptance coverage;
- clearer errors, safer defaults, and API ergonomics;
- `FromResult`/`FromContext` binding, broader capability-graph execution, and ordering;
- exact database-operation adapters;
- broader deterministic execution compilation described in the roadmap;
- documentation, diagrams, and reproducible bug reports.

For substantial behavior or architecture changes, open an
[issue](https://github.com/tugrulguner/summonpot/issues/new/choose) first so the public
contract and security boundary stay coherent.

Development uses [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/tugrulguner/summonpot.git
cd summonpot
uv sync --all-extras
make check
```

Every user-facing change needs an issue-backed or generated orphan Towncrier fragment. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Roadmap

The long-term goal is one stable endpoint declaration with the least-powerful sufficient
executor behind it:

```text
one fully resolved operation path  -> no-model deterministic executor
bounded semantic choice remains    -> agentic executor
no legal path                      -> typed deterministic error
```

The ordering, security constraints, non-goals, and shipped foundation live in
[ROADMAP.md](ROADMAP.md).

## Help summonpot grow

If the endpoint-first approach is useful to you:

- [Star the repository](https://github.com/tugrulguner/summonpot) so more Python
  developers can find it.
- Build one small endpoint and
  [report the friction](https://github.com/tugrulguner/summonpot/issues/new/choose).
- Share a real use case, add an executable example, or contribute to a roadmap milestone.

Early feedback is especially valuable because the public contract is small and the next
execution layers are being designed around it now.

## License

[MIT](LICENSE)
