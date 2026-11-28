"""Multiple decision frontiers preserve local execution and shared authority."""

import asyncio

import pytest
from pydantic import BaseModel, Field

from summonpot import (
    AgentChoice,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)
from summonpot.runtime import Runtime

starts = []
packaging_unavailable = False


class Request(BaseModel):
    units: int = Field(ge=1, le=100)
    goods_cents: int = Field(ge=0)
    rush: bool = False
    protective: bool = False


class Option(BaseModel):
    name: str
    cents: int


class Line(BaseModel):
    name: str
    cents: int


class Quote(BaseModel):
    shipping: str
    packaging: str
    total_cents: int


def shipping_options(units: int, rush: bool) -> list[Option]:
    starts.append("shipping_options")
    options = [
        Option(name="standard", cents=250 + 50 * units),
        Option(name="express", cents=600 + 80 * units),
    ]
    return [x for x in options if not rush or x.name == "express"]


shipping_offers = Operation(
    shipping_options, bind={"units": FromRequest("units"), "rush": FromRequest("rush")}
)


def choose_shipping(option: Option) -> Line:
    starts.append("choose_shipping")
    return Line(name=option.name, cents=option.cents)


shipping = Operation(
    choose_shipping, bind={"option": AgentChoice(from_result=shipping_offers)}
)


def packaging_options(units: int, protective: bool) -> list[Option]:
    starts.append("packaging_options")
    if packaging_unavailable:
        return []
    options = [
        Option(name="lightweight", cents=100 + 15 * units),
        Option(name="protective", cents=250 + 25 * units),
    ]
    return [x for x in options if not protective or x.name == "protective"]


packaging_offers = Operation(
    packaging_options,
    bind={"units": FromRequest("units"), "protective": FromRequest("protective")},
)


def choose_packaging(option: Option) -> Line:
    starts.append("choose_packaging")
    return Line(name=option.name, cents=option.cents)


packaging = Operation(
    choose_packaging, bind={"option": AgentChoice(from_result=packaging_offers)}
)


def finish(
    goods_cents: int,
    shipping_cents: int,
    packaging_cents: int,
    shipping_name: str,
    packaging_name: str,
) -> Quote:
    starts.append("finish")
    return Quote(
        shipping=shipping_name,
        packaging=packaging_name,
        total_cents=goods_cents + shipping_cents + packaging_cents,
    )


quote = Operation(
    finish,
    bind={
        "goods_cents": FromRequest("goods_cents"),
        "shipping_cents": FromResult(shipping, "cents"),
        "packaging_cents": FromResult(packaging, "cents"),
        "shipping_name": FromResult(shipping, "name"),
        "packaging_name": FromResult(packaging, "name"),
    },
)


def make_graph():
    app = Summon("two-independent-choices")

    @app("/quote")
    def quote_endpoint(
        request: Request,
        a=Required(shipping_offers, calls=Exactly(1)),
        b=Required(shipping, calls=Exactly(1)),
        c=Required(packaging_offers, calls=Exactly(1)),
        d=Required(packaging, calls=Exactly(1)),
        e=Required(quote, calls=Exactly(1)),
    ) -> Quote:
        """Choose the lowest-price offered shipping and packaging and return the exact quote."""
        ...

    return app


def test_two_independent_singletons_execute_without_model(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Singleton graph attempted model resolution")

    monkeypatch.setattr(Runtime, "model_for", forbidden)
    monkeypatch.setattr(Runtime, "_agent_for", forbidden)
    starts.clear()
    app = make_graph()
    result = asyncio.run(
        app._runtime.call(
            app.endpoints[0],
            {"units": 2, "goods_cents": 1000, "rush": True, "protective": True},
        )
    )
    assert result == Quote(shipping="express", packaging="protective", total_cents=2060)
    assert starts == [
        "shipping_options",
        "choose_shipping",
        "packaging_options",
        "choose_packaging",
        "finish",
    ]


def evidence_model(calls, *, stale_frontier=False):
    import json

    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel

    prior_tokens = []

    def choose(messages, info):
        assert not info.function_tools
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart) and isinstance(p.content, str)
        )
        frontier = json.loads(text.splitlines()[-1])
        calls.append([d["argument"] for d in frontier.values()])
        selected = {
            slot: min(domain["candidates"], key=lambda item: item["value"]["cents"])[
                "token"
            ]
            for slot, domain in frontier.items()
        }
        current = list(selected.values())
        if stale_frontier and prior_tokens:
            selected = {slot: prior_tokens[0] for slot in selected}
        prior_tokens.extend(current)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, selected)])

    return FunctionModel(choose)


def test_distinct_consumer_frontiers_share_request_budget():
    from fastapi.testclient import TestClient
    from pydantic_ai.usage import UsageLimits

    from summonpot.server import build_app

    for limit, status in [(1, 429), (2, 200)]:
        starts.clear()
        calls = []
        app = make_graph()
        app._runtime = Runtime(
            model=evidence_model(calls),
            retries=0,
            usage_limits=UsageLimits(request_limit=limit),
        )
        with TestClient(build_app(app)) as client:
            response = client.post("/quote", json={"units": 2, "goods_cents": 1000})
        assert response.status_code == status
        assert len(calls) == limit
        if status == 429:
            assert starts == [
                "shipping_options",
                "choose_shipping",
                "packaging_options",
            ]
        else:
            assert response.json() == {
                "shipping": "standard",
                "packaging": "lightweight",
                "total_cents": 1480,
            }
            assert starts == [
                "shipping_options",
                "choose_shipping",
                "packaging_options",
                "choose_packaging",
                "finish",
            ]


def test_later_empty_domain_keeps_earlier_decision_and_effects(monkeypatch):
    import sys

    from fastapi.testclient import TestClient

    from summonpot.server import build_app

    monkeypatch.setattr(sys.modules[__name__], "packaging_unavailable", True)
    starts.clear()
    calls = []
    app = make_graph()
    app._runtime = Runtime(model=evidence_model(calls), retries=0)
    with TestClient(build_app(app)) as client:
        response = client.post("/quote", json={"units": 2, "goods_cents": 1000})
    assert response.status_code == 409
    assert calls == [["option"]]
    assert starts == ["shipping_options", "choose_shipping", "packaging_options"]


def test_three_choice_arguments_have_no_arbitrary_two_choice_cap():
    from fastapi.testclient import TestClient
    from pydantic_ai.usage import UsageLimits

    from summonpot.server import build_app

    def insurance_options(units: int) -> list[Option]:
        return [
            Option(name="basic", cents=35 * units),
            Option(name="extra", cents=80 * units),
        ]

    insurance = Operation(insurance_options, bind={"units": FromRequest("units")})

    def join(
        shipping_option: Option,
        packaging_option: Option,
        insurance_option: Option,
        goods: int,
    ) -> Quote:
        return Quote(
            shipping=shipping_option.name,
            packaging=packaging_option.name,
            total_cents=goods
            + shipping_option.cents
            + packaging_option.cents
            + insurance_option.cents,
        )

    final = Operation(
        join,
        bind={
            "shipping_option": AgentChoice(from_result=shipping_offers),
            "packaging_option": AgentChoice(from_result=packaging_offers),
            "insurance_option": AgentChoice(from_result=insurance),
            "goods": FromRequest("goods_cents"),
        },
    )
    calls = []
    app = Summon(
        "three-choices",
        runtime=Runtime(
            model=evidence_model(calls),
            usage_limits=UsageLimits(request_limit=1),
            retries=0,
        ),
    )

    @app("/quote")
    def endpoint(
        request: Request,
        a=Required(shipping_offers, calls=Exactly(1)),
        b=Required(packaging_offers, calls=Exactly(1)),
        c=Required(insurance, calls=Exactly(1)),
        d=Required(final, calls=Exactly(1)),
    ) -> Quote:
        """Choose three independent permitted values and return the exact quote."""
        ...

    with TestClient(build_app(app)) as client:
        response = client.post("/quote", json={"units": 2, "goods_cents": 1000})
    assert response.status_code == 200
    assert response.json()["total_cents"] == 1000 + 350 + 130 + 70
    assert calls == [["shipping_option", "packaging_option", "insurance_option"]]


def test_prior_frontier_token_cannot_authorize_later_consumer():
    from fastapi.testclient import TestClient

    from summonpot.server import build_app

    starts.clear()
    calls = []
    app = make_graph()
    app._runtime = Runtime(model=evidence_model(calls, stale_frontier=True), retries=0)
    with TestClient(build_app(app)) as client:
        response = client.post("/quote", json={"units": 2, "goods_cents": 1000})
    assert response.status_code == 502
    assert calls == [["option"], ["option"]]
    assert starts == ["shipping_options", "choose_shipping", "packaging_options"]


@pytest.mark.parametrize("block,expected", [(False, 200), (True, 504)])
def test_absolute_deadline_spans_later_decision_frontier(block, expected):
    import json

    from fastapi.testclient import TestClient
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel

    from summonpot.server import build_app

    starts.clear()
    calls = []

    async def choose(messages, info):
        assert not info.function_tools
        text = next(
            p.content
            for m in reversed(messages)
            for p in m.parts
            if isinstance(p, UserPromptPart) and isinstance(p.content, str)
        )
        domain = json.loads(text.splitlines()[-1])["decision_slot_0"]
        calls.append(True)
        if block and len(calls) == 2:
            await asyncio.sleep(2)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"decision_slot_0": domain["candidates"][0]["token"]},
                )
            ]
        )

    app = make_graph()
    app._runtime = Runtime(model=FunctionModel(choose), timeout=0.2, retries=0)
    with TestClient(build_app(app)) as client:
        response = client.post("/quote", json={"units": 2, "goods_cents": 1000})
    assert response.status_code == expected
    assert len(calls) == 2
    assert starts == (
        ["shipping_options", "choose_shipping", "packaging_options"]
        if block
        else [
            "shipping_options",
            "choose_shipping",
            "packaging_options",
            "choose_packaging",
            "finish",
        ]
    )
