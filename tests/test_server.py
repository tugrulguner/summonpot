"""Tests for the HTTP server — verifies FastAPI routes are built from endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import (
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from summonpot import Depends, Summon, __version__
from summonpot.server import build_app


class AnalysisRequest(BaseModel):
    text: str = Field(min_length=3)
    max_topics: int = Field(default=3, ge=1, le=10, alias="maxTopics")


class AnalysisResponse(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]
    topics: list[str]


class TypedRequest(BaseModel):
    customer_id: UUID = Field(alias="customerId")
    created_at: datetime = Field(alias="createdAt")


def test_build_app_creates_route(mock_runtime):
    summon = mock_runtime(mock_response="Hello, world!")

    @summon("/hello")
    def hello(name: str) -> str:
        """Greet someone."""
        return ""

    app = build_app(summon)
    client = TestClient(app)
    response = client.post("/hello", json={"name": "world"})
    assert response.status_code == 200
    assert response.json() == "Hello, world!"


def test_openapi_describes_the_endpoint_framework_not_an_agent_framework(mock_runtime):
    schema = TestClient(build_app(mock_runtime())).get("/openapi.json").json()

    assert schema["info"]["description"] == (
        "A contract-first Python framework for modernizing APIs for AI through exact "
        "application behavior and explicitly bounded agent-owned decisions."
    )
    assert "signature-first" not in schema["info"]["description"].lower()
    assert "every endpoint is an agent" not in schema["info"]["description"].lower()


def test_build_app_uses_pydantic_request_and_response_models(mock_runtime):
    summon = mock_runtime(
        mock_response={"sentiment": "positive", "topics": ["agents", "apis"]}
    )

    @summon("/analyze")
    def analyze(request: AnalysisRequest) -> AnalysisResponse:
        """Analyze text."""
        ...

    client = TestClient(build_app(summon))
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/analyze"]["post"]

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert request_schema == {"$ref": "#/components/schemas/AnalysisRequest"}
    assert response_schema == {"$ref": "#/components/schemas/AnalysisResponse"}

    valid = client.post("/analyze", json={"text": "Great framework"})
    assert valid.status_code == 200
    assert valid.json() == {"sentiment": "positive", "topics": ["agents", "apis"]}
    summon._runtime.call.assert_awaited_once_with(
        summon.endpoints[0], {"text": "Great framework", "maxTopics": 3}
    )

    invalid = client.post("/analyze", json={"text": "x"})
    assert invalid.status_code == 422


def test_http_boundary_preserves_typed_and_prompt_request_views(mock_runtime):
    summon = mock_runtime(mock_response="ok")

    @summon("/typed-values")
    def typed_values(request: TypedRequest) -> str:
        """Use typed request values."""
        ...

    customer_id = UUID("12345678-1234-5678-1234-567812345678")
    created_at = datetime(2026, 8, 24, 12, 30, tzinfo=UTC)
    response = TestClient(build_app(summon)).post(
        "/typed-values",
        json={"customerId": str(customer_id), "createdAt": created_at.isoformat()},
    )

    assert response.status_code == 200
    passed = summon._runtime.call.await_args.args[1]
    assert passed == {
        "customerId": str(customer_id),
        "createdAt": "2026-08-24T12:30:00Z",
    }
    assert passed.typed == {
        "customer_id": customer_id,
        "created_at": created_at,
    }


def test_dependency_parameters_do_not_leak_into_http_contract(mock_runtime):
    def analyze_records(text: str) -> dict[str, str]:
        """Run exact deterministic analysis."""
        return {"text": text}

    summon = mock_runtime(
        mock_response={"sentiment": "positive", "topics": ["capabilities"]}
    )

    @summon("/analyze")
    def analyze(
        request: AnalysisRequest,
        records=Depends(analyze_records),
    ) -> AnalysisResponse:
        """Analyze using only the declared operation."""
        raise AssertionError("declarative endpoint body must not execute")

    client = TestClient(build_app(summon))
    operation = client.get("/openapi.json").json()["paths"]["/analyze"]["post"]

    assert operation.get("parameters", []) == []
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalysisRequest"
    }
    response = client.post("/analyze", json={"text": "Exact operation"})
    assert response.status_code == 200
    assert response.json() == {
        "sentiment": "positive",
        "topics": ["capabilities"],
    }


def test_request_schema_preserves_unions_generics_and_any(mock_runtime):
    """The HTTP contract must match the signature, not a parsed display string."""
    summon = mock_runtime(mock_response="ok")

    @summon("/typed")
    def typed(
        q: str,
        limit: int | None = None,
        payload: Any = None,
        items: list[int] | None = None,
    ) -> str:
        """Typed endpoint."""
        return ""

    client = TestClient(build_app(summon))
    properties = client.get("/openapi.json").json()["components"]["schemas"][
        "typedRequest"
    ]["properties"]

    # A nullable parameter stays nullable instead of collapsing to its first member.
    assert properties["limit"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    # Any imposes no constraint instead of silently becoming a string.
    assert "type" not in properties["payload"]

    assert client.post("/typed", json={"q": "x", "limit": None}).status_code == 200
    assert (
        client.post("/typed", json={"q": "x", "payload": {"a": 1}}).status_code == 200
    )
    assert client.post("/typed", json={"q": "x", "limit": 5}).status_code == 200


def test_request_schema_validates_generic_element_types(mock_runtime):
    """list[int] used to fail open, handing the agent the wrong types."""
    summon = mock_runtime(mock_response="ok")

    @summon("/items")
    def items(values: list[int]) -> str:
        """Items endpoint."""
        return ""

    client = TestClient(build_app(summon))

    assert client.post("/items", json={"values": [1, 2]}).status_code == 200
    assert client.post("/items", json={"values": ["a", "b"]}).status_code == 422


@pytest.mark.parametrize(
    ("raised", "expected_status", "expected_detail"),
    [
        (
            UsageLimitExceeded("request limit of 2 exceeded"),
            429,
            "exceeded its configured usage limit",
        ),
        (TimeoutError(), 504, "timed out"),
        (
            ModelHTTPError(status_code=429, model_name="openai:gpt-4o-mini"),
            429,
            "status 429",
        ),
        (
            ModelHTTPError(status_code=500, model_name="openai:gpt-4o-mini"),
            502,
            "status 500",
        ),
        (
            UnexpectedModelBehavior("Exceeded maximum retries"),
            502,
            "did not satisfy the endpoint contract",
        ),
    ],
)
def test_runtime_failures_map_to_stable_http_responses(
    raised, expected_status, expected_detail
):
    """Every one of these used to reach the caller as an opaque 500."""
    summon = Summon("svc")

    @summon("/research")
    def research(query: str) -> str:
        """Research a topic."""
        return ""

    class FailingRuntime:
        async def call(self, endpoint, params):
            raise raised

    summon._runtime = FailingRuntime()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    response = client.post("/research", json={"query": "agents"})

    assert response.status_code == expected_status
    assert expected_detail in response.json()["detail"]


def test_unexpected_capability_failure_still_surfaces_as_a_server_error():
    """An error inside user code is a genuine 500, not a mislabelled gateway error."""
    summon = Summon("svc")

    @summon("/research")
    def research(query: str) -> str:
        """Research a topic."""
        return ""

    class FailingRuntime:
        async def call(self, endpoint, params):
            raise ValueError("the accounts database is down")

    summon._runtime = FailingRuntime()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    assert client.post("/research", json={"query": "agents"}).status_code == 500


def test_build_app_requires_body_fields(mock_runtime):
    summon = mock_runtime()

    @summon("/strict")
    def strict(required_field: int) -> str:
        """Strict endpoint."""
        return ""

    app = build_app(summon)
    client = TestClient(app)
    # Missing required field → 422 validation error
    response = client.post("/strict", json={})
    assert response.status_code == 422


def test_build_app_openapi_has_endpoints():
    summon = Summon("svc")

    @summon("/analyze")
    def analyze(text: str) -> dict:
        """Analyze text."""
        return {}

    app = build_app(summon)
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    operation = paths["/analyze"]["post"]
    assert schema["info"]["version"] == __version__
    assert operation.get("parameters", []) == []
    assert operation["requestBody"]["required"] is True
    assert "/analyze" in paths
    assert "post" in paths["/analyze"]


def test_build_app_no_body_route_hides_internal_context(mock_runtime):
    summon = mock_runtime(mock_response="ready")

    @summon("/health")
    def health() -> str:
        """Report readiness."""
        return ""

    client = TestClient(build_app(summon))
    operation = client.get("/openapi.json").json()["paths"]["/health"]["post"]

    assert operation.get("parameters", []) == []
    assert "requestBody" not in operation
    response = client.post("/health")
    assert response.status_code == 200
    assert response.json() == "ready"


@pytest.mark.parametrize(
    "raised",
    [
        UnexpectedModelBehavior("invalid model output: PRIVATE_CUSTOMER_RECORD_123"),
        UsageLimitExceeded("limit hit: PRIVATE_CUSTOMER_RECORD_123"),
    ],
)
def test_runtime_exception_text_is_not_returned_to_the_caller(raised, caplog):
    """Agent-loop exceptions can carry rejected model output or tool-call context."""
    summon = Summon("svc")

    @summon("/research")
    def research(query: str) -> str:
        """Research a topic."""
        return ""

    class FailingRuntime:
        async def call(self, endpoint, params):
            raise raised

    summon._runtime = FailingRuntime()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    with caplog.at_level(logging.WARNING, logger="summonpot.server"):
        response = client.post("/research", json={"query": "agents"})

    assert "PRIVATE_CUSTOMER_RECORD_123" not in response.text
    # The operator still gets the detail.
    assert "PRIVATE_CUSTOMER_RECORD_123" in caplog.text


def test_get_endpoint_is_registered_as_get_with_query_parameters(mock_runtime):
    """method= used to be accepted and discarded, always producing a POST route."""
    summon = mock_runtime(mock_response="Berlin is sunny.")

    @summon("/forecast", method="GET")
    def forecast(city: str, days: int = 3) -> str:
        """Report the forecast."""
        return ""

    client = TestClient(build_app(summon))
    operation = client.get("/openapi.json").json()["paths"]["/forecast"]

    assert set(operation) == {"get"}
    parameters = {p["name"]: p for p in operation["get"]["parameters"]}
    assert set(parameters) == {"city", "days"}
    assert parameters["city"]["in"] == "query"
    assert parameters["city"]["required"] is True
    assert parameters["days"]["required"] is False
    assert "requestBody" not in operation["get"]

    response = client.get("/forecast?city=Berlin&days=5")
    assert response.status_code == 200
    assert response.json() == "Berlin is sunny."
    summon._runtime.call.assert_awaited_once_with(
        summon.endpoints[0], {"city": "Berlin", "days": 5}
    )


def test_get_endpoint_rejects_a_post(mock_runtime):
    summon = mock_runtime(mock_response="ok")

    @summon("/forecast", method="GET")
    def forecast(city: str) -> str:
        """Report the forecast."""
        return ""

    client = TestClient(build_app(summon))

    assert client.post("/forecast", json={"city": "Berlin"}).status_code == 405


def test_put_and_delete_methods_are_registered(mock_runtime):
    summon = mock_runtime(mock_response="ok")

    @summon("/records", method="PUT")
    def replace_record(record_id: str, payload: str) -> str:
        """Replace a record."""
        return ""

    @summon("/records/purge", method="DELETE")
    def purge_record(record_id: str) -> str:
        """Purge a record."""
        return ""

    paths = TestClient(build_app(summon)).get("/openapi.json").json()["paths"]

    # PUT keeps a JSON body; DELETE takes query parameters.
    assert set(paths["/records"]) == {"put"}
    assert "requestBody" in paths["/records"]["put"]
    assert set(paths["/records/purge"]) == {"delete"}
    assert "requestBody" not in paths["/records/purge"]["delete"]


def test_query_parameters_keep_their_resolved_type_contract(mock_runtime):
    """A GET must honour the signature, not a lossy display-string approximation."""
    summon = mock_runtime(mock_response="ok")

    @summon("/lookup", method="GET")
    def lookup(
        value: int | str,
        count: int = 1,
        tags: list[int] | None = None,
    ) -> str:
        """Look up a record."""
        return ""

    client = TestClient(build_app(summon))
    operation = client.get("/openapi.json").json()["paths"]["/lookup"]["get"]
    assert {p["name"]: p["in"] for p in operation["parameters"]} == {
        "value": "query",
        "count": "query",
        "tags": "query",
    }

    # A union member that is not the first one is accepted.
    assert client.get("/lookup?value=customer-alpha").status_code == 200
    # A scalar is still coerced to its declared type.
    assert client.get("/lookup?value=x&count=7").status_code == 200
    # A generic keeps its element type: repeated values parse, wrong ones are rejected.
    assert client.get("/lookup?value=x&tags=1&tags=2").status_code == 200
    assert client.get("/lookup?value=x&tags=a").status_code == 422
    # Required-ness survives.
    assert client.get("/lookup").status_code == 422

    summon._runtime.call.assert_any_await(
        summon.endpoints[0], {"value": "x", "count": 1, "tags": [1, 2]}
    )


def test_query_route_uses_the_shared_runtime_error_mapping():
    """A parameterised GET must get the same stable statuses as a body route."""
    summon = Summon("svc")

    @summon("/forecast", method="GET")
    def forecast(city: str) -> str:
        """Report the forecast."""
        return ""

    class FailingRuntime:
        async def call(self, endpoint, params):
            raise UnexpectedModelBehavior("invalid output: PRIVATE_SENTINEL_123")

    summon._runtime = FailingRuntime()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    response = client.get("/forecast?city=Berlin")

    assert response.status_code == 502
    assert "PRIVATE_SENTINEL_123" not in response.text


def test_build_app_never_raises_for_a_registered_endpoint(mock_runtime):
    """Unsupported query shapes are refused at registration, not inside FastAPI."""
    summon = mock_runtime(mock_response="ok")

    @summon("/forecast", method="GET")
    def forecast(city: str, days: list[int] | None = None) -> str:
        """Report the forecast."""
        return ""

    assert build_app(summon) is not None


def test_literal_query_parameter_enforces_its_allowed_values(mock_runtime):
    """A Literal is a valid query contract: accepted in-set, 422 out of set."""
    summon = mock_runtime(mock_response="ok")

    @summon("/tickets", method="GET")
    def tickets(status: Literal["open", "closed"] = "open") -> str:
        """List tickets by status."""
        return ""

    client = TestClient(build_app(summon))
    parameter = client.get("/openapi.json").json()["paths"]["/tickets"]["get"][
        "parameters"
    ][0]

    assert parameter["in"] == "query"
    assert client.get("/tickets?status=open").status_code == 200
    assert client.get("/tickets?status=closed").status_code == 200
    assert client.get("/tickets?status=banana").status_code == 422


def test_annotated_query_parameter_enforces_its_constraint(mock_runtime):
    summon = mock_runtime(mock_response="ok")

    @summon("/search", method="GET")
    def search(term: Annotated[str, Field(min_length=3)]) -> str:
        """Search for a term."""
        return ""

    client = TestClient(build_app(summon))

    assert client.get("/search?term=abc").status_code == 200
    assert client.get("/search?term=ab").status_code == 422


def test_sequence_query_parameter_keeps_its_own_constraint(mock_runtime):
    """The query marker must not replace the annotation's declared FieldInfo."""
    summon = mock_runtime(mock_response="ok")

    @summon("/batch", method="GET")
    def batch(ids: Annotated[list[int], Field(min_length=2)]) -> str:
        """Look up several records."""
        return ""

    client = TestClient(build_app(summon))

    assert client.get("/batch?ids=1&ids=2").status_code == 200
    # One value violates min_length=2, which the signature declares.
    assert client.get("/batch?ids=1").status_code == 422


def test_sequence_query_parameter_keeps_its_element_constraint(mock_runtime):
    summon = mock_runtime(mock_response="ok")

    @summon("/batch", method="GET")
    def batch(ids: list[Annotated[int, Field(ge=1)]] | None = None) -> str:
        """Look up several records."""
        return ""

    client = TestClient(build_app(summon))

    assert client.get("/batch?ids=1&ids=2").status_code == 200
    # 0 violates the element constraint ge=1.
    assert client.get("/batch?ids=0&ids=2").status_code == 422


def test_unconstrained_sequence_query_parameter_still_binds(mock_runtime):
    """The marker is still required for a sequence to bind at all."""
    summon = mock_runtime(mock_response="ok")

    @summon("/batch", method="GET")
    def batch(ids: list[int] | None = None) -> str:
        """Look up several records."""
        return ""

    client = TestClient(build_app(summon))

    assert client.get("/batch?ids=1&ids=2").status_code == 200
    summon._runtime.call.assert_any_await(summon.endpoints[0], {"ids": [1, 2]})
    assert client.get("/batch?ids=a").status_code == 422


def test_one_path_serves_both_methods(mock_runtime):
    """The pair must reach FastAPI as two operations on a single path."""
    summon = mock_runtime(mock_response="ok")

    @summon("/orders", method="GET")
    def list_orders(status: str = "open") -> str:
        """List orders."""
        return ""

    @summon("/orders", method="POST")
    def place_order(item: str) -> str:
        """Place an order."""
        return ""

    client = TestClient(build_app(summon))
    operations = client.get("/openapi.json").json()["paths"]["/orders"]

    assert set(operations) == {"get", "post"}
    assert client.get("/orders?status=open").status_code == 200
    assert client.post("/orders", json={"item": "widget"}).status_code == 200


def test_provider_misconfiguration_is_reported_not_swallowed(caplog):
    """A missing API key is the most likely first-run failure."""
    from pydantic_ai.exceptions import UserError

    summon = Summon("svc")

    @summon("/research")
    def research(query: str) -> str:
        """Research a topic."""
        return ""

    class UnconfiguredRuntime:
        async def call(self, endpoint, params):
            raise UserError("Set the `OPENAI_API_KEY` environment variable")

    summon._runtime = UnconfiguredRuntime()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="summonpot.server"):
        response = client.post("/research", json={"query": "agents"})

    assert response.status_code == 500
    # The caller gets a stable message, not the raw provider text.
    assert (
        response.json()["detail"] == "Endpoint is not configured. See the server logs."
    )
    assert "OPENAI_API_KEY" not in response.text
    # The operator gets the diagnosis and a way forward.
    assert "not configured" in caplog.text
    assert "SUMMONPOT_MODEL=test" in caplog.text
    assert "OPENAI_API_KEY" in caplog.text


# --- #78: the URL is the single authority for a path parameter ---------------


class _RecordingRuntime:
    """Captures exactly what the runtime was handed."""

    def __init__(self) -> None:
        self.prompt: dict = {}
        self.typed: dict = {}

    async def call(self, endpoint, params):
        self.prompt = dict(params)
        self.typed = dict(getattr(params, "typed", params))
        return "ok"


def _customer_app(annotation: type = str):
    summon = Summon("svc")

    def update_customer(customer_id: annotation, name: str) -> str:  # type: ignore[valid-type]
        """Update one customer."""
        return ""

    update_customer.__annotations__["customer_id"] = annotation
    summon.summon("/customers/{customer_id}", method="POST")(update_customer)

    runtime = _RecordingRuntime()
    summon._runtime = runtime
    return summon, runtime


def test_path_parameter_is_declared_in_the_openapi_schema():
    summon, _ = _customer_app()
    operation = build_app(summon).openapi()["paths"]["/customers/{customer_id}"]["post"]

    declared = [(p["name"], p["in"], p["required"]) for p in operation["parameters"]]
    assert declared == [("customer_id", "path", True)]


def test_path_parameter_is_excluded_from_the_generated_body_model():
    """It cannot be in two places, so it is in exactly one."""
    summon, _ = _customer_app()
    schemas = build_app(summon).openapi()["components"]["schemas"]

    model = next(v for k, v in schemas.items() if k.endswith("Request"))
    assert sorted(model["properties"]) == ["name"]


def test_the_url_value_reaches_the_runtime():
    summon, runtime = _customer_app()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    assert client.post("/customers/url-id", json={"name": "Ada"}).status_code == 200
    assert runtime.prompt["customer_id"] == "url-id"
    assert runtime.typed["customer_id"] == "url-id"


def test_a_conflicting_body_identifier_does_not_win():
    """The reported case: URL says one thing, body says another.

    Before, the runtime received the body value and the URL was decorative.
    """
    summon, runtime = _customer_app()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    response = client.post(
        "/customers/url-id", json={"customer_id": "body-id", "name": "Ada"}
    )

    assert response.status_code == 200
    assert runtime.prompt["customer_id"] == "url-id"
    assert runtime.typed["customer_id"] == "url-id"


def test_a_typed_path_parameter_arrives_converted():
    """`typed` keeps the validated Python value; `prompt` stays JSON-safe."""
    summon, runtime = _customer_app(int)
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    assert client.post("/customers/42", json={"name": "Ada"}).status_code == 200
    assert runtime.typed["customer_id"] == 42
    assert isinstance(runtime.typed["customer_id"], int)


def test_an_unconvertible_path_value_is_a_422():
    summon, _ = _customer_app(int)
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    assert client.post("/customers/nope", json={"name": "Ada"}).status_code == 422


def test_a_route_without_placeholders_is_unchanged():
    """Regression: the body handler's signature is synthesised either way."""
    summon = Summon("svc")

    @summon.summon("/customers", method="POST")
    def create_customer(name: str) -> str:
        """Create one customer."""
        return ""

    runtime = _RecordingRuntime()
    summon._runtime = runtime
    app = build_app(summon)
    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/customers", json={"name": "Ada"}).status_code == 200
    assert runtime.prompt == {"name": "Ada"}
    assert app.openapi()["paths"]["/customers"]["post"].get("parameters") is None


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_bodyless_path_parameters_still_work(method):
    """GET/DELETE bound placeholders before this change and must still."""
    summon = Summon("svc")

    def get_customer(customer_id: str) -> str:
        """Read one customer."""
        return ""

    summon.summon("/customers/{customer_id}", method=method)(get_customer)
    runtime = _RecordingRuntime()
    summon._runtime = runtime
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    response = client.request(method, "/customers/url-id")

    assert response.status_code == 200
    assert runtime.prompt["customer_id"] == "url-id"


def _path_only_app(method: str = "POST"):
    """A body method whose every declared parameter comes from the URL."""
    summon = Summon("svc")

    def touch_item(item_id: int) -> str:
        """Touch one item."""
        return ""

    summon.summon("/items/{item_id}", method=method)(touch_item)
    runtime = _RecordingRuntime()
    summon._runtime = runtime
    return summon, runtime


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_a_path_only_body_route_needs_no_body(method):
    """The URL already carries every value, so requiring a body is a dead end.

    Before, the generated request model was an empty-but-required body: the
    call was answered 422 and the runtime was never reached.
    """
    summon, runtime = _path_only_app(method)
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    response = client.request(method, "/items/7")

    assert response.status_code == 200
    assert runtime.typed["item_id"] == 7
    assert runtime.prompt["item_id"] == 7


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_a_path_only_body_route_declares_no_request_body(method):
    """OpenAPI must not advertise a body the route does not read."""
    summon, _ = _path_only_app(method)
    operation = build_app(summon).openapi()["paths"]["/items/{item_id}"][method.lower()]

    assert "requestBody" not in operation
    assert [(p["name"], p["in"]) for p in operation["parameters"]] == [
        ("item_id", "path")
    ]


def test_a_path_only_body_route_still_validates_the_url_value():
    summon, _ = _path_only_app()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    assert client.post("/items/not-an-int").status_code == 422


def test_a_path_only_body_route_tolerates_a_sent_body():
    """A client that sends a body anyway is not punished; the URL still wins."""
    summon, runtime = _path_only_app()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    response = client.post("/items/7", json={"item_id": 99})

    assert response.status_code == 200
    assert runtime.typed["item_id"] == 7


def test_a_mixed_route_still_requires_its_body():
    """Guard the other side: dropping the body model must stay path-only."""
    summon, _ = _customer_app()
    client = TestClient(build_app(summon), raise_server_exceptions=False)

    assert client.post("/customers/url-id").status_code == 422


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_a_path_parameter_may_be_called_body(method):
    """`body` is the URL author's word to use; it is not ours to reserve.

    The synthetic request-body parameter shares one namespace with the path
    parameters, so hard-coding its name put two parameters called `body` in the
    signature and `build_app()` raised `ValueError: duplicate parameter name`
    -- the whole application refusing to start over a legal route.
    """
    summon = Summon("svc")

    def store_item(body: str, note: str) -> str:
        """A route whose URL segment is spelled `body`."""
        return ""

    summon.summon("/items/{body}", method=method)(store_item)
    runtime = _RecordingRuntime()
    summon._runtime = runtime

    app = build_app(summon)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.request(method, "/items/from-url", json={"note": "n"})

    assert response.status_code == 200
    # The URL segment owns the name, and the body keeps its own field.
    assert runtime.typed["body"] == "from-url"
    assert runtime.typed["note"] == "n"

    operation = app.openapi()["paths"]["/items/{body}"][method.lower()]
    assert [p["name"] for p in operation["parameters"]] == ["body"]
    model = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = app.openapi()["components"]["schemas"][model.rsplit("/", 1)[1]]
    assert sorted(schema["properties"]) == ["note"]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/items/{ item_id }", id="both-sides"),
        pytest.param("/items/{item_id }", id="trailing"),
        pytest.param("/items/{ item_id}", id="leading"),
        pytest.param("/items/{item id}", id="internal-space"),
    ],
)
def test_a_non_canonical_placeholder_is_rejected_not_normalised(path):
    """Stripping the braces made the declaration and the served route disagree.

    `/items/{ item_id }` passed registration as `item_id`, but Starlette was
    handed the unstripped template, so the names never matched at request time.
    """
    summon = Summon("svc")

    def touch_item(item_id: int) -> str:
        """Touch one item."""
        return ""

    with pytest.raises(ValueError, match="not a valid Python identifier"):
        summon.summon(path, method="GET")(touch_item)


def test_a_canonical_placeholder_is_still_accepted():
    """The guard must not fire on the ordinary spelling."""
    summon = Summon("svc")

    def touch_item(item_id: int) -> str:
        """Touch one item."""
        return ""

    summon.summon("/items/{item_id}", method="GET")(touch_item)
    assert summon.endpoints[0].path == "/items/{item_id}"
