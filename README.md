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

You define routes with a function signature, a docstring, and tools. The framework owns the agentic runtime — the LLM call loop, tool orchestration, structured output, and streaming. You don't configure an agent. You define an endpoint. The agent is summoned.

```python
from summonpot import Pot

pot = Pot("my-service", tools=[search_web])

@pot.summon("/research")
def research_topic(query: str, depth: str = "standard") -> str:
    """Research this topic thoroughly and return a comprehensive report."""

@pot.summon("/analyze")
def analyze_sentiment(text: str) -> dict:
    """Analyze the text and return a JSON object with sentiment and topics."""

pot.serve()
```

Call it like any API:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "quantum computing", "depth": "deep"}'
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

You also need an OpenAI-compatible API key:

```bash
export SUMMONPOT_API_KEY=sk-...          # or OPENAI_API_KEY
export SUMMONPOT_MODEL=gpt-4o-mini        # optional, default gpt-4o-mini
export SUMMONPOT_BASE_URL=https://api.openai.com/v1   # optional
```

## Quick Start

Create a file `app.py`:

```python
from summonpot import Pot

# A tool available to every endpoint
def search_web(query: str) -> list[dict]:
    """Search the web for information."""
    return [{"query": query, "result": "..."}]

pot = Pot("my-service", tools=[search_web])

@pot.summon("/research")
def research_topic(query: str, depth: str = "standard") -> str:
    """Research this topic thoroughly and return a comprehensive report."""

@pot.summon("/summarize")
def summarize(text: str) -> str:
    """Summarize the given text into key bullet points."""

@pot.summon("/analyze")
def analyze_sentiment(text: str) -> dict:
    """Analyze the text and return a JSON object with sentiment and topics."""
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

## How it works

summonpot inspects your endpoint function:

- **Docstring** → becomes the system prompt the agent follows
- **Parameters** → become the JSON request schema (validated by Pydantic)
- **Return type** → becomes the output contract (structured JSON for non-`str` types)
- **Tools** → exposed to the agent via function calling, so it can act, not just answer

The framework owns the LLM call loop, tool orchestration, and structured-output enforcement. You provide intent — the endpoint.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SUMMONPOT_API_KEY` | `OPENAI_API_KEY` | API key for the LLM provider |
| `SUMMONPOT_BASE_URL` | `OPENAI_BASE_URL` or `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `SUMMONPOT_MODEL` | `gpt-4o-mini` | Default model for all endpoints |

Per-endpoint overrides:

```python
@pot.summon("/research", model="gpt-4o", stream=True)
def research_topic(query: str) -> str:
    """Research this topic."""
```

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
