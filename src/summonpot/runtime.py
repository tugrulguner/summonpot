"""Provider-neutral endpoint runtime for direct and agent-backed execution."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from summonpot._execution import (
    _CompiledEndpoint,
    _CompiledTool,
    _EndpointRun,
    _new_run,
    _prepare_request,
    _register_endpoint,
    _registered_plan,
)
from summonpot.contracts import AgentChoice, FromRequest
from summonpot.models import EndpointDef

ModelSpec = Model | str


class _OperationOutputError(RuntimeError):
    """A capability returned a value outside its declared output contract."""


def _tracked_operation(tool: _CompiledTool) -> Any:
    """Build a model tool backed by one immutable compiled capability."""
    visible_signature = tool.visible_signature

    async def execute(*args: Any, **kwargs: Any) -> Any:
        # Pydantic AI injects RunContext first positionally. Its parameter name is
        # intentionally collision-free in the declared signature below.
        ctx, *capability_args = args
        if not tool.enforce_bound_exactly_once:
            result = await _call_capability(tool.fn, *capability_args, **kwargs)
            async with ctx.deps.lock:
                ctx.deps.states[tool.identity].succeeded += 1
            return result

        supplied = visible_signature.bind(*capability_args, **kwargs).arguments
        return await _invoke_bound_operation(tool, ctx.deps, supplied)

    annotations = {
        name: annotation
        for name, annotation in tool.annotations.items()
        if name == "return" or name in visible_signature.parameters
    }
    context_name = "ctx"
    while context_name in visible_signature.parameters:
        context_name = f"_{context_name}"
    context_parameter = inspect.Parameter(
        context_name,
        inspect.Parameter.POSITIONAL_ONLY,
        annotation=RunContext[_EndpointRun],
    )
    execute.__name__ = tool.name
    execute.__doc__ = tool.description or None
    execute.__signature__ = visible_signature.replace(  # type: ignore[attr-defined]
        parameters=[context_parameter, *visible_signature.parameters.values()]
    )
    execute.__annotations__ = {
        context_name: RunContext[_EndpointRun],
        **annotations,
    }
    return execute


async def _invoke_bound_operation(
    tool: _CompiledTool,
    run: _EndpointRun,
    supplied: Mapping[str, Any],
) -> Any:
    """Invoke one enforced operation through the shared trusted-value kernel."""
    values = dict(supplied)
    for binding in tool.bindings:
        if isinstance(binding.source, FromRequest):
            try:
                values[binding.argument] = run.request[binding.source.field]
            except KeyError:
                raise RuntimeError(
                    f"Required request field {binding.source.field!r} is unavailable."
                ) from None
        elif isinstance(binding.source, AgentChoice):
            # Already validated against the model-visible signature when agent-owned.
            continue

    state = run.states[tool.identity]
    async with run.lock:
        if tool.maximum is not None and state.started >= tool.maximum:
            raise ModelRetry(
                f"Capability {tool.name!r} may run exactly once and has already started."
            )
        state.started += 1
        state.running += 1

    try:
        result = await _call_with_values(tool, values)
        assert tool.output_adapter is not None
        try:
            validated = tool.output_adapter.validate_python(result)
        except ValidationError as exc:
            raise _OperationOutputError(
                f"Capability {tool.name!r} returned an invalid declared output."
            ) from exc
    finally:
        async with run.lock:
            state.running -= 1

    async with run.lock:
        state.succeeded += 1
    return validated


async def _call_with_values(tool: _CompiledTool, values: dict[str, Any]) -> Any:
    """Invoke a compiled callable while preserving positional-only parameters."""
    positional: list[Any] = []
    positional_parameters = [
        parameter
        for parameter in tool.signature.parameters.values()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
    ]
    supplied_positions = [
        index
        for index, parameter in enumerate(positional_parameters)
        if parameter.name in values
    ]
    if supplied_positions:
        for parameter in positional_parameters[: max(supplied_positions) + 1]:
            if parameter.name in values:
                positional.append(values[parameter.name])
            else:
                positional.append(parameter.default)

    keywords = {
        name: values[name]
        for name, parameter in tool.signature.parameters.items()
        if name in values and parameter.kind is not inspect.Parameter.POSITIONAL_ONLY
    }
    return await _call_capability(tool.fn, *positional, **keywords)


async def _call_capability(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run sync and async application callables without blocking the event loop."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    result = await asyncio.to_thread(fn, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class Runtime:
    """Execute summonpot endpoints through the least-powerful shipped path."""

    def __init__(
        self,
        model: ModelSpec | None = None,
        *,
        retries: int = 1,
        usage_limits: UsageLimits | None = None,
        timeout: float | None = None,
    ) -> None:
        self._model = model
        self.retries = retries
        self.usage_limits = usage_limits
        self.timeout = timeout
        self._agents: dict[
            tuple[int, str], tuple[_CompiledEndpoint, Agent[_EndpointRun, Any]]
        ] = {}

    def _plan_for(self, endpoint: EndpointDef) -> _CompiledEndpoint:
        plan = _registered_plan(endpoint)
        if plan is None:
            # Compatibility for EndpointDef instances constructed outside Summon. They
            # have not passed authoritative registration validation, so they must not
            # activate the direct path from mutable inspection metadata alone.
            plan = _register_endpoint(endpoint, allow_direct=False)
        return plan

    @property
    def default_model(self) -> ModelSpec:
        """Resolve the default model at call time."""
        configured = self._model or os.environ.get(
            "SUMMONPOT_MODEL", "openai:gpt-4o-mini"
        )
        return _normalize_model(configured)

    def model_for(self, endpoint: EndpointDef) -> ModelSpec:
        """Resolve a compiled endpoint override or the runtime default."""
        configured = self._plan_for(endpoint).model
        if configured is not None:
            return _normalize_model(configured)
        return self.default_model

    async def call(
        self,
        endpoint: EndpointDef,
        params: Mapping[str, Any],
    ) -> Any:
        """Run an endpoint with provider-neutral tools and typed output."""
        plan = self._plan_for(endpoint)
        request = _prepare_request(plan, params)
        run = _new_run(plan, request)
        if plan.direct_tool is not None:
            async with asyncio.timeout(self.timeout):
                return await _invoke_bound_operation(
                    plan.tools[plan.direct_tool], run, {}
                )

        agent = self._agent_for(endpoint)
        message = self._build_user_message(plan, request)
        async with asyncio.timeout(self.timeout):
            result = await agent.run(message, deps=run, usage_limits=self.usage_limits)
        output = result.output

        if plan.output_model is not None:
            return output
        if plan.return_type.lower() not in ("str", "string", "any"):
            try:
                return json.loads(output)
            except (json.JSONDecodeError, TypeError):
                return output
        return output

    def _agent_for(self, endpoint: EndpointDef) -> Agent[_EndpointRun, Any]:
        """Return the cached agent for one immutable endpoint plan and model."""
        plan = self._plan_for(endpoint)
        model = self.model_for(endpoint)
        key = (id(plan), str(model))
        cached = self._agents.get(key)
        if cached is not None and cached[0] is plan:
            return cached[1]

        agent = self._build_agent(plan, model)
        self._agents[key] = (plan, agent)
        return agent

    def _build_agent(
        self, plan: _CompiledEndpoint, model: ModelSpec
    ) -> Agent[_EndpointRun, Any]:
        tools = [
            Tool(
                _tracked_operation(tool),
                name=tool.name,
                description=tool.description,
                takes_ctx=True,
            )
            for tool in plan.tools
        ]
        agent = Agent(
            model,
            output_type=plan.output_model or str,
            system_prompt=plan.description,
            tools=tools,
            retries=self.retries,
            deps_type=_EndpointRun,
        )

        @agent.output_validator
        def require_declared_operations(
            ctx: RunContext[_EndpointRun], output: Any
        ) -> Any:
            missing = [
                tool.name
                for tool in plan.tools
                if tool.required
                and ctx.deps.states[tool.identity].succeeded < tool.minimum
            ]
            if missing:
                names = ", ".join(sorted(missing))
                raise ModelRetry(
                    f"Required capabilities must run before final output: {names}"
                )
            return output

        return agent

    def _build_user_message(
        self,
        plan: _CompiledEndpoint,
        params: Mapping[str, Any],
    ) -> str:
        """Build a provider-neutral user message from JSON-safe values."""
        parts = [f"Endpoint: {plan.path}"]
        if params:
            parts.append("Parameters:")
            for key, value in params.items():
                parts.append(f"  {key}: {json.dumps(value, default=str)}")
        return "\n".join(parts)


# Built-in models that need no provider and no API key.
PROVIDERLESS_MODELS = frozenset({"test"})


def _normalize_model(model: ModelSpec) -> ModelSpec:
    """Keep explicit providers and preserve legacy OpenAI model names."""
    if not isinstance(model, str) or ":" in model:
        return model
    if model in PROVIDERLESS_MODELS:
        return model
    return f"openai:{model}"


__all__ = ["Runtime"]
