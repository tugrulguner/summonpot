# summonpot

<p align="center">
  <img src="summonpot.png" alt="SummonPot" width="600">
</p>

[![CI](https://github.com/tugrulguner/summonpot/actions/workflows/ci.yml/badge.svg)](https://github.com/tugrulguner/summonpot/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/summonpot)](https://pypi.org/project/summonpot/)
[![Python versions](https://img.shields.io/pypi/pyversions/summonpot)](https://pypi.org/project/summonpot/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**An AI-native API framework. Every endpoint is an agent that runs automatically.**

summonpot is a **full API framework** — with routing, validation, middleware, and serving — but built for the era where APIs don't just respond, they reason. Define routes. The framework runs the agents. No agent configuration. No framework ontology. Just endpoints that think.

You define routes with Pydantic request and response models, a docstring, and exact deterministic capabilities. The framework owns the agentic runtime — the LLM call loop, capability orchestration, structured output, and streaming. You don't configure an agent or write handler glue. You define an endpoint. The agent is summoned.

```python
from pydantic import BaseModel, Field
from summonpot import Pot


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3)
    depth: int = Field(default=3, ge=1, le=5)


class ResearchResponse(BaseModel):
    summary: str
    key_findings: list[str]
    sources: list[str]


pot = Pot("my-service", tools=[search_web])


@pot.summon("/research")
def research_topic(request: ResearchRequest) -> ResearchResponse:
    """Research this topic thoroughly and return a sourced report."""
    raise NotImplementedError


pot.serve()
```

Call it like any API:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "quantum computing", "depth": 5}'
```

Behind the scenes, an agent runs — it thinks, uses tools, calls the LLM, enforces structured output, and returns the result. But you never wrote an agent. You wrote a route.

## Why another framework?

Every existing approach to building agentic APIs has the same problem: you first learn an agent framework (LangChain, CrewAI, AutoGen), then bolt an HTTP server on top. The mental model is "configure an agent" — which is complex, brittle, and framework-y.

summonpot flips this: the **web framework IS the agent framework**. The routing is the agentic logic. The decorator is the incantation. The framework owns the smart parts.

| | Existing frameworks | summonpot |
|---|---|---|
| Mental model | "Configure an agent" | "Define an endpoint" |
| Surface area | Large (chains, agents, tools, memory, callbacks...) | Tiny (decorator + types + docstring) |
| API exposure | Bolt-on HTTP wrapper | Native (routing IS the agent) |
| Complexity | User manages the loop | Framework owns the loop, user provides intent |
| Testability | Heavy mocking required | Test like a regular HTTP endpoint |
| Onboarding | Learn the framework's ontology | If you know HTTP, you know this |

## Installation

```bash
pip install summonpot            # core
pip install summonpot[serve]     # + HTTP server (FastAPI/uvicorn)
pip install summonpot[cli]       # + Typer CLI
pip install summonpot[all]       # everything
```

Install the provider you want to use:

```bash
pip install "summonpot[openai]"       # OpenAI
pip install "summonpot[anthropic]"    # Anthropic
pip install "summonpot[google]"       # Google Gemini
pip install "summonpot[groq]"         # Groq
pip install "summonpot[mistral]"      # Mistral
pip install "summonpot[openrouter]"   # OpenRouter
pip install "summonpot[xai]"          # xAI
pip install "summonpot[all]"          # serving, CLI, and every provider
```

Choose a model with an explicit `provider:model` identifier and set that provider's standard API-key environment variable:

```bash
export SUMMONPOT_MODEL=anthropic:claude-sonnet-4-5
export ANTHROPIC_API_KEY=...
```

OpenRouter keeps the upstream provider and model in the portion after the first colon:

```bash
export SUMMONPOT_MODEL=openrouter:anthropic/claude-sonnet-4
export OPENROUTER_API_KEY=...
```

The endpoint API does not change between providers. Unprefixed legacy model names such as `gpt-4o-mini` continue to resolve as `openai:gpt-4o-mini`.

## Quick Start

Create a file `app.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field
from summonpot import Pot


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1)
    max_topics: int = Field(default=5, ge=1, le=20)


class AnalyzeResponse(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]
    topics: list[str]
    explanation: str


# A tool available to every endpoint
def search_web(query: str) -> list[dict]:
    """Search the web for information."""
    return [{"query": query, "result": "..."}]


pot = Pot("my-service", tools=[search_web])


@pot.summon("/analyze")
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze the text and return its sentiment, topics, and explanation."""
    raise NotImplementedError
```

Serve it:

```bash
summonpot serve app.py                  # serves on 0.0.0.0:8000
summonpot serve app.py --port 9000
```

Or from Python:

```python
pot.serve()                             # 0.0.0.0:8000
pot.serve(host="127.0.0.1", port=9000)
```

## The Summoning Model

| Concept | As summoning |
|---|---|
| Route definition | "At this path, I summon..." |
| Docstring | The incantation (system prompt) |
| Tools | Ingredients placed in the circle |
| Parameters | What the summoner brings |
| Return type | What appears |
| `stream=True` | You asked it to speak continuously |

## Declarative dependencies

An endpoint signature can combine one Pydantic request model, exact deterministic dependencies, and one Pydantic response model:

```python
from pydantic import BaseModel, Field
from summonpot import Depends, Required


class PlanRequest(BaseModel):
    goal: str
    constraints: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    steps: list[str]
    risks: list[str]


def load_constraints(goal: str) -> list[str]:
    """Load exact stored constraints for the goal."""
    return []


def check_capacity(goal: str) -> dict:
    """Check current capacity with deterministic business logic."""
    return {"available": True}


@pot.summon("/plan")
def plan(
    request: PlanRequest,
    stored_constraints=Depends(load_constraints),
    capacity=Required(check_capacity),
) -> PlanResponse:
    """Create an actionable plan that respects every constraint."""
    raise NotImplementedError
```

The signature is the complete execution contract. The decorated function is declarative—the runtime does not execute its body.

- The request model alone defines and validates incoming JSON.
- The response model defines OpenAPI output and validates the final result.
- `Depends(operation)` gives the agent an exact deterministic operation it may call.
- `Required(operation)` rejects final output until the exact operation has run successfully.
- Dependencies never become HTTP request fields.
- The agent receives no undeclared application operations.
- Provider output is retried within a bounded budget when it violates the response contract or skips a required operation.

A Pydantic endpoint has exactly one request parameter plus any declarative dependencies. Put all incoming fields inside the request model so there is one clear JSON body.

## How it works

summonpot inspects your endpoint function:

- **Docstring** → becomes the fixed endpoint goal
- **Pydantic request model** → becomes the validated JSON request body and OpenAPI input schema
- **Pydantic response model** → becomes the provider's structured-output schema, runtime validator, and OpenAPI response schema
- **Dependencies** → become the endpoint's closed set of optional or mandatory deterministic capabilities

The framework owns the agent loop, capability orchestration, required-operation enforcement, and structured-output validation. The endpoint body contains no handler code.

See [Declarative capability endpoints](docs/declarative-capabilities.md) for the execution and security contract.

## Provider and model configuration

Summonpot uses provider-qualified model identifiers. Provider SDKs, authentication, tool calling, structured-output negotiation, and model-specific behavior are handled internally by the provider-agnostic runtime.

| Provider | Install extra | Model example | API-key variable |
|---|---|---|---|
| OpenAI | `summonpot[openai]` | `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `summonpot[anthropic]` | `anthropic:claude-sonnet-4-5` | `ANTHROPIC_API_KEY` |
| Google | `summonpot[google]` | `google:gemini-2.5-flash` | `GOOGLE_API_KEY` |
| Groq | `summonpot[groq]` | `groq:llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Mistral | `summonpot[mistral]` | `mistral:mistral-large-latest` | `MISTRAL_API_KEY` |
| OpenRouter | `summonpot[openrouter]` | `openrouter:anthropic/claude-sonnet-4` | `OPENROUTER_API_KEY` |
| xAI | `summonpot[xai]` | `xai:grok-4` | `XAI_API_KEY` |

`SUMMONPOT_MODEL` sets the default for every endpoint:

```bash
export SUMMONPOT_MODEL=openrouter:anthropic/claude-sonnet-4
```

An endpoint can override it without changing its request, response, or tools:

```python
@pot.summon(
    "/research",
    model="anthropic:claude-sonnet-4-5",
    stream=True,
)
def research_topic(request: ResearchRequest) -> ResearchResponse:
    """Research this topic."""
    raise NotImplementedError
```

Pydantic AI is an internal runtime dependency. Summonpot users do not construct Pydantic AI agents or provider clients; the stable public contract remains `Pot`, `@pot.summon`, tools, and Pydantic endpoint models.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/tugrulguner/summonpot.git
cd summonpot
uv sync --all-extras
```

```bash
make check    # lint + typecheck + test
make lint     # ruff check + format check
make test     # pytest
make format   # auto-format
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for pull-request and single-source release instructions.

## License

MIT
