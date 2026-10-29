"""Multiple producer-backed choices share one guarded local execution path."""

import asyncio

from pydantic import BaseModel
from pydantic_ai.models.function import FunctionModel

from summonpot import AgentChoice, Exactly, FromRequest, Operation, Required, Summon
from summonpot._execution import _register_endpoint
from summonpot.runtime import Runtime


class Request(BaseModel):
    product_id: str


class Product(BaseModel):
    identifier: str


class Delivery(BaseModel):
    identifier: str


class Receipt(BaseModel):
    product: str
    delivery: str


def multiple_choices_app(
    events, *, multi_deliveries=False, empty_deliveries=False, many_deliveries=False
):
    def find_products(product_id: str) -> list[Product]:
        events.append(("products", product_id))
        return [Product(identifier=product_id)]

    products = Operation(
        find_products,
        bind={"product_id": FromRequest("product_id")},
        output=list[Product],
    )

    def deliveries(product: Product) -> list[Delivery]:
        events.append(("deliveries", product.identifier))
        choices = (
            []
            if empty_deliveries
            else [str(i) for i in range(129)]
            if many_deliveries
            else ["standard", "express"]
            if multi_deliveries
            else ["standard"]
        )
        return [Delivery(identifier=choice) for choice in choices]

    delivery_options = Operation(
        deliveries,
        bind={"product": AgentChoice(from_result=products)},
        output=list[Delivery],
    )

    def commit(product: Product, delivery: Delivery) -> Receipt:
        events.append(("commit", product.identifier, delivery.identifier))
        return Receipt(product=product.identifier, delivery=delivery.identifier)

    commit_order = Operation(
        commit,
        bind={
            "product": AgentChoice(from_result=products),
            "delivery": AgentChoice(from_result=delivery_options),
        },
        output=Receipt,
    )
    app = Summon("multi-choice")

    @app("/commit")
    def endpoint(
        request: Request,
        found=Required(products, calls=Exactly(1)),
        options=Required(delivery_options, calls=Exactly(1)),
        receipt=Required(commit_order, calls=Exactly(1)),
    ) -> Receipt:
        """Find a product, its delivery options, and commit the order."""
        ...

    return app


def test_two_successive_singleton_choices_never_resolve_model(monkeypatch):
    events = []
    app = multiple_choices_app(events)
    plan = _register_endpoint(app.endpoints[0])
    assert plan.result_dependent_order == (0, 1, 2)

    def forbidden(*args, **kwargs):
        raise AssertionError("all-singleton chain must not touch the model")

    for name in ("model_for", "_agent_for", "_build_agent"):
        monkeypatch.setattr(Runtime, name, forbidden)
    result = asyncio.run(Runtime().call(app.endpoints[0], {"product_id": "P1"}))
    assert result == Receipt(product="P1", delivery="standard")
    assert events == [
        ("products", "P1"),
        ("deliveries", "P1"),
        ("commit", "P1", "standard"),
    ]


def test_singleton_and_multiple_arguments_handoff_once_without_partial_commit():
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    events = []
    app = multiple_choices_app(events, multi_deliveries=True)
    rounds = []

    def model(messages, info):
        tools = info.function_tools
        rounds.append([tool.name for tool in tools])
        if not tools:
            from pydantic_ai.messages import TextPart

            return ModelResponse(parts=[TextPart("untrusted terminal text")])
        assert [tool.name for tool in tools] == ["commit"]
        schema = tools[0].parameters_json_schema
        arguments = {
            name: field["enum"][0]
            for name, field in schema["properties"].items()
            if "enum" in field
        }
        assert set(arguments) == {"product", "delivery"}
        return ModelResponse(parts=[ToolCallPart("commit", arguments)])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"product_id": "P2"})
    )
    assert result == Receipt(product="P2", delivery="standard")
    assert rounds == [["commit"], []]
    assert events == [
        ("products", "P2"),
        ("deliveries", "P2"),
        ("commit", "P2", "standard"),
    ]


def test_empty_or_oversized_later_domain_precedes_model_and_consumer():
    import pytest
    from fastapi.testclient import TestClient

    from summonpot.runtime import _ChoiceUnavailableError
    from summonpot.server import build_app

    for domain in ("empty", "oversized"):
        events = []
        app = multiple_choices_app(
            events,
            multi_deliveries=domain == "oversized",
            empty_deliveries=domain == "empty",
            many_deliveries=domain == "oversized",
        )

        def forbidden_model(messages, info):
            raise AssertionError("unavailable domain must not call a model")

        with pytest.raises(_ChoiceUnavailableError):
            asyncio.run(
                Runtime(model=FunctionModel(forbidden_model)).call(
                    app.endpoints[0], {"product_id": domain}
                )
            )
        assert events == [("products", domain), ("deliveries", domain)]

        http_events = []
        http_app = multiple_choices_app(
            http_events,
            empty_deliveries=domain == "empty",
            many_deliveries=domain == "oversized",
        )
        with TestClient(build_app(http_app)) as client:
            response = client.post("/commit", json={"product_id": domain})
        assert response.status_code == 409
        assert http_events == [("products", domain), ("deliveries", domain)]


def test_later_multi_choice_handoff_returns_canonical_terminal_result():
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

    events = []
    app = multiple_choices_app(events, multi_deliveries=True)
    seen = []

    def model(messages, info):
        tools = info.function_tools
        seen.append([tool.name for tool in tools])
        if not tools:
            return ModelResponse(parts=[TextPart("forged receipt")])
        by_name = {tool.name: tool for tool in tools}
        if "deliveries" in by_name:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "deliveries",
                        {
                            "product": by_name["deliveries"].parameters_json_schema[
                                "properties"
                            ]["product"]["enum"][0]
                        },
                    )
                ]
            )
        tool = by_name["commit"]
        properties = tool.parameters_json_schema["properties"]
        arguments = {
            name: value["enum"][0]
            for name, value in properties.items()
            if "enum" in value
        }
        assert set(arguments) == {"product", "delivery"}
        return ModelResponse(parts=[ToolCallPart("commit", arguments)])

    result = asyncio.run(
        Runtime(model=FunctionModel(model)).call(app.endpoints[0], {"product_id": "P3"})
    )
    assert result == Receipt(product="P3", delivery="standard")
    assert seen == [["commit"], []]
    assert events == [
        ("products", "P3"),
        ("deliveries", "P3"),
        ("commit", "P3", "standard"),
    ]
