"""Agent runtime — owns the LLM call loop for summonpot."""

from __future__ import annotations

import json
import os
from typing import Any

from summonpot.models import EndpointDef


class Runtime:
    """Agent execution engine.

    Calls an OpenAI-compatible API to fulfill an endpoint's intent.
    In v0.1 this is a single LLM call with function calling (no multi-step loop).
    The loop will deepen in v0.2+.
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("SUMMONPOT_API_KEY") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        self.base_url = os.environ.get(
            "SUMMONPOT_BASE_URL",
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.default_model = os.environ.get("SUMMONPOT_MODEL", "gpt-4o-mini")

    async def call(
        self,
        endpoint: EndpointDef,
        params: dict[str, Any],
    ) -> Any:
        """Execute an endpoint's agentic logic with the given parameters.

        Builds the LLM request, calls the API, and returns the structured result.
        """
        if not self.api_key:
            raise RuntimeError(
                "No API key configured. Set SUMMONPOT_API_KEY or OPENAI_API_KEY."
            )

        model = endpoint.model or self.default_model
        system_prompt = endpoint.description

        # Build the user message — describe what the caller wants
        user_message = self._build_user_message(endpoint, params)

        # Build tool definitions for function calling
        tools = [t.to_openai_tool() for t in endpoint.tools]

        # Build the request body
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        if endpoint.output_model is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": endpoint.output_model.__name__,
                    "schema": endpoint.output_model.model_json_schema(),
                },
            }
        elif endpoint.return_type.lower() in ("str", "string"):
            # Plain text response — no structured output enforcement
            pass
        elif endpoint.return_type in ("dict", "object", "Any"):
            body["response_format"] = {"type": "json_object"}
        else:
            # For typed responses, try to use structured outputs
            body["response_format"] = {"type": "json_object"}

        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # Make the API call
        import httpx

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()

        message = data["choices"][0]["message"]

        # Handle tool calls
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                tool_name = tc["function"]["name"]
                tool_args = json.loads(tc["function"]["arguments"])
                # Find the matching tool and execute it
                for t in endpoint.tools:
                    if t.name == tool_name:
                        tool_result = await t.call(**tool_args)
                        # Append tool result to messages
                        body["messages"].append(message)
                        body["messages"].append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(tool_result, default=str),
                            }
                        )
                        break

            # Get final response after tool calls
            body.pop("tools", None)
            body.pop("tool_choice", None)
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
            message = data["choices"][0]["message"]

        content = message.get("content", "")

        # Parse structured output if needed
        if endpoint.output_model is not None:
            return endpoint.output_model.model_validate_json(content)

        if endpoint.return_type.lower() not in ("str", "string", "any"):
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return content

        return content

    def _build_user_message(
        self,
        endpoint: EndpointDef,
        params: dict[str, Any],
    ) -> str:
        """Build a user message from the endpoint's parameters."""
        parts = [f"Endpoint: {endpoint.path}"]
        if params:
            parts.append("Parameters:")
            for key, value in params.items():
                parts.append(f"  {key}: {json.dumps(value, default=str)}")
        return "\n".join(parts)
