"""Example summonpot app with first-class Pydantic endpoint contracts."""

from typing import Literal

from pydantic import BaseModel, Field

from summonpot import Pot


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3)
    depth: int = Field(default=3, ge=1, le=5)


class ResearchResponse(BaseModel):
    summary: str
    key_findings: list[str]
    sources: list[str]


class SentimentRequest(BaseModel):
    text: str = Field(min_length=1)
    max_topics: int = Field(default=5, ge=1, le=20)


class SentimentResponse(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]
    topics: list[str]
    explanation: str


def search_web(query: str) -> list[dict]:
    """Search the web for information."""
    return [{"query": query, "result": "example result"}]


pot = Pot("example-service", tools=[search_web])


@pot.summon("/research")
def research(request: ResearchRequest) -> ResearchResponse:
    """Research this topic thoroughly and return a sourced report."""
    raise NotImplementedError


@pot.summon("/analyze")
def analyze(request: SentimentRequest) -> SentimentResponse:
    """Analyze the text and return its sentiment, topics, and explanation."""
    raise NotImplementedError
