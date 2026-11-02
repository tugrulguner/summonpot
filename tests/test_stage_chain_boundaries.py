"""Adversarial public-runtime boundaries for repeated stage chains."""

import asyncio
import threading
import time
from typing import Annotated, Any, Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from summonpot import (
    AgentChoice,
    Between,
    Exactly,
    FromContext,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime, _ContextError, _OperationOutputError


class Request(BaseModel):
    key: str


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant: str
    level: str = "x"


class Prepared(BaseModel):
    key: str


class Snapshot(BaseModel):
    key: str
    choice: str


class Checked(BaseModel):
    key: str
    choice: str


class Report(BaseModel):
    key: str
    choice: str
    tenant: str


def make_chain(
    *,
    suffix_context=False,
    invalid_second=False,
    runtime=None,
    prepare_hook=None,
    auth_events=None,
):
    events = []
    prompts = []
    decisions = {}
    decision_lock = threading.Lock()

    async def prepare(key: str, tenant: str) -> Prepared:
        events.append(("prepare", key, tenant))
        if prepare_hook is not None:
            await prepare_hook()
        return Prepared(key=key)

    def inspect(key: str, choice: Literal["first", "second"]) -> Snapshot:
        events.append(("inspect", key, choice))
        if invalid_second and choice == "second":
            return cast(Any, {"key": 4, "choice": choice})
        return Snapshot(key=key, choice=choice)

    def check(
        key: str,
        choice: str,
        tenant: str = "",
        level: Annotated[str, Field(min_length=3)] = "okay",
    ) -> Checked:
        events.append(("check", key, choice, tenant))
        return Checked(key=key, choice=choice)

    def finalize(key: str, choice: str, tenant: str) -> Report:
        events.append(("finalize", key, choice, tenant))
        return Report(key=key, choice=choice, tenant=tenant)

    def model(messages, info):
        prompt = next(
            str(part.content)
            for message in messages
            for part in getattr(message, "parts", ())
            if isinstance(part, UserPromptPart)
        )
        prompts.append(prompt)
        assert not info.function_tools
        key = prompt.split('"key": "', 1)[1].split('"', 1)[0]
        with decision_lock:
            ordinal = decisions.get(key, 0)
            decisions[key] = ordinal + 1
        next_value = ("first", "second", "finish")[ordinal]
        payload = (
            {"decision": "finish"}
            if next_value == "finish"
            else {"decision": "invoke", "argument_0": next_value}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    prepared = Operation(
        prepare,
        bind={"key": FromRequest("key"), "tenant": FromContext("tenant")},
        output=Prepared,
    )
    repeated = Operation(
        inspect,
        bind={"key": FromResult(prepared, "key"), "choice": AgentChoice()},
        output=Snapshot,
    )
    check_bind: dict[str, Any] = {
        "key": FromResult(repeated, "key", invocation="final"),
        "choice": FromResult(repeated, "choice", invocation="final"),
    }
    if suffix_context:
        check_bind["level"] = FromContext("level")
    checked = Operation(check, bind=check_bind, output=Checked)
    final = Operation(
        finalize,
        bind={
            "key": FromResult(checked, "key"),
            "choice": FromResult(checked, "choice"),
            "tenant": FromContext("tenant"),
        },
        output=Report,
    )

    def authenticate(request) -> Principal:
        if auth_events is not None:
            auth_events.append("auth")
        return Principal(tenant=request.headers["x-tenant"])

    app = Summon(
        "stage-boundary",
        runtime=runtime or Runtime(model=FunctionModel(model), retries=0),
        context=authenticate,
    )

    @app("/run")
    def endpoint(
        request: Request,
        a=Required(prepared, calls=Exactly(1)),
        b=Required(repeated, calls=Between(1, 3)),
        c=Required(checked, calls=Exactly(1)),
        d=Required(final, calls=Exactly(1)),
    ) -> Report:
        """Prepare, inspect, verify and report."""
        ...

    return app, events, prompts, model


def trusted(tenant):
    return Principal(tenant=tenant)


def run(runtime, app, key, tenant):
    return asyncio.run(
        runtime.call(app.endpoints[0], {"key": key}, context=trusted(tenant))
    )


def test_concurrent_trusted_principals_are_isolated_and_not_projected_to_model():
    app, events, prompts, _ = make_chain()
    runtime = app._runtime

    async def exercise():
        return await asyncio.gather(
            *(
                runtime.call(
                    app.endpoints[0], {"key": f"k{i}"}, context=trusted(f"tenant-{i}")
                )
                for i in range(2)
            )
        )

    results = asyncio.run(exercise())
    assert {result.tenant for result in results} == {"tenant-0", "tenant-1"}
    assert {(e[1], e[2]) for e in events if e[0] == "prepare"} == {
        ("k0", "tenant-0"),
        ("k1", "tenant-1"),
    }
    assert all("tenant-" not in prompt for prompt in prompts), prompts


def test_suffix_only_context_constraint_is_preflighted_before_prefix_or_model():
    app, events, prompts, _ = make_chain(suffix_context=True)
    # A correct principal is admitted; the test replaces the suffix receiver with a
    # narrower annotation in a separately compiled declaration below via bad context.
    plan = app._runtime._plan_for(app.endpoints[0])
    assert (
        sum(
            binding.source == FromContext("tenant")
            for tool in plan.tools
            for binding in tool.bindings
        )
        >= 2
    )
    with pytest.raises(_ContextError):
        asyncio.run(
            app._runtime.call(
                app.endpoints[0],
                {"key": "x"},
                context=Principal(tenant="tenant", level="x"),
            )
        )
    assert events == [] and prompts == []


def test_invalid_later_repeated_output_aborts_without_suffix_or_terminal():
    app, events, _, _ = make_chain(invalid_second=True)
    with pytest.raises(_OperationOutputError):
        run(app._runtime, app, "x", "tenant")
    assert [event[0] for event in events] == ["prepare", "inspect", "inspect"]


def test_receiving_prefix_result_is_used_on_every_repeated_start():
    app, events, _, _ = make_chain()
    run(app._runtime, app, "x", "tenant")
    starts = [event for event in events if event[0] == "inspect"]
    assert starts == [
        ("inspect", "x", "first"),
        ("inspect", "x", "second"),
    ]


def test_explicit_function_tool_quota_rejects_before_context_or_prefix():
    calls = []
    runtime = Runtime(
        model=FunctionModel(lambda messages, info: ModelResponse(parts=[])),
        retries=0,
        usage_limits=UsageLimits(tool_calls_limit=3),
    )
    from fastapi.testclient import TestClient

    from summonpot.server import build_app

    app, events, _, _ = make_chain(runtime=runtime, auth_events=calls)
    with TestClient(build_app(app)) as client:
        response = client.post(
            "/run", json={"key": "x"}, headers={"x-tenant": "tenant"}
        )
    assert response.status_code == 500
    assert calls == [] and events == []


def test_cancellation_after_prefix_entry_prevents_model_and_stage_start():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_prefix():
        entered.set()
        await release.wait()

    app, events, prompts, _ = make_chain(prepare_hook=hold_prefix)

    async def exercise():
        task = asyncio.create_task(
            app._runtime.call(app.endpoints[0], {"key": "x"}, context=trusted("tenant"))
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()

    asyncio.run(exercise())
    assert [event[0] for event in events] == ["prepare"]
    assert prompts == []


def test_deadline_expiring_during_prefix_return_blocks_model_resolution():
    from summonpot.runtime import _runtime_deadline

    async def expire_deadline():
        _runtime_deadline.set(time.monotonic() - 1)

    app, events, prompts, _ = make_chain(prepare_hook=expire_deadline)
    with pytest.raises(TimeoutError):
        run(app._runtime, app, "x", "tenant")
    assert [event[0] for event in events] == ["prepare"]
    assert prompts == []
