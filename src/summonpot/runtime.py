"""Provider-agnostic agent runtime for summonpot."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model

from summonpot.models import EndpointDef

ModelSpec = Model | str


class Runtime:
    """Execute summonpot endpoints through a provider-agnostic agent engine."""

    def __init__(
        self,
        model: ModelSpec | None = None,
        *,
        retries: int = 1,
    ) -> None:
        configured_model = model or os.environ.get(
            "SUMMONPOT_MODEL", "openai:gpt-4o-mini"
        )
        self.default_model = _normalize_model(configured_model)
        self.retries = retries

    def model_for(self, endpoint: EndpointDef) -> ModelSpec:
        """Resolve an endpoint override or the runtime's default model."""
        if endpoint.model is not None:
            return _normalize_model(endpoint.model)
        return self.default_model

    async def call(
        self,
        endpoint: EndpointDef,
        params: dict[str, Any],
    ) -> Any:
        """Run an endpoint with provider-neutral tools and typed output."""
        output_type: Any = endpoint.output_model or str
        tools = [
            Tool(
                tool.fn,
                name=tool.name,
                description=tool.description,
                takes_ctx=False,
            )
            for tool in endpoint.tools
        ]
        agent = Agent(
            self.model_for(endpoint),
            output_type=output_type,
            system_prompt=endpoint.description,
            tools=tools,
            retries=self.retries,
        )
        result = await agent.run(self._build_user_message(endpoint, params))
        output = result.output

        if endpoint.output_model is not None:
            return output
        if endpoint.return_type.lower() not in ("str", "string", "any"):
            try:
                return json.loads(output)
            except (json.JSONDecodeError, TypeError):
                return output
        return output

    def _build_user_message(
        self,
        endpoint: EndpointDef,
        params: dict[str, Any],
    ) -> str:
        """Build a provider-neutral user message from endpoint parameters."""
        parts = [f"Endpoint: {endpoint.path}"]
        if params:
            parts.append("Parameters:")
            for key, value in params.items():
                parts.append(f"  {key}: {json.dumps(value, default=str)}")
        return "\n".join(parts)


def _normalize_model(model: ModelSpec) -> ModelSpec:
    """Keep explicit providers and preserve legacy OpenAI model names."""
    if not isinstance(model, str) or ":" in model:
        return model
    return f"openai:{model}"
