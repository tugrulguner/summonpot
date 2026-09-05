"""Tests for the Summon class — endpoint registration and introspection."""

from __future__ import annotations

import inspect
from typing import Annotated, Literal
from uuid import UUID

import pytest
from pydantic import BaseModel, Field

from summonpot import Depends, Required, Summon
from summonpot.tools import tool


class ResearchRequest(BaseModel):
    query: str
    depth: int = 1


class ResearchResponse(BaseModel):
    summary: str
    sources: list[str]


def test_summon_init():
    summon = Summon("svc")
    assert summon.name == "svc"
    assert summon.endpoints == []


def test_summon_registers_endpoint():
    summon = Summon("svc")

    @summon("/research")
    def research_topic(query: str, depth: str = "standard") -> str:
        """Research this topic."""
        return ""

    assert len(summon.endpoints) == 1
    ep = summon.endpoints[0]
    assert ep.path == "/research"
    assert ep.name == "research_topic"
    assert ep.description == "Research this topic."
    assert ep.return_type == "str"
    assert [p.name for p in ep.parameters] == ["query", "depth"]
    assert ep.parameters[0].required is True
    assert ep.parameters[1].required is False
    assert ep.parameters[1].default == "standard"


def test_registered_endpoint_declaration_is_not_directly_callable():
    summon = Summon("svc")
    executed: list[str] = []

    @summon("/research")
    def research_topic(query: str) -> str:
        """Research this topic."""
        executed.append(query)
        return query

    with pytest.raises(TypeError) as error:
        research_topic("typed contracts")

    assert str(error.value) == (
        "Summonpot endpoint declaration 'research_topic' is not directly callable. "
        "Serve the Summon application or invoke POST /research."
    )
    assert executed == []


def test_registered_declaration_preserves_its_public_signature():
    summon = Summon("svc")

    def expected(query: str, depth: int = 1) -> str: ...

    @summon("/research")
    def research_topic(query: str, depth: int = 1) -> str:
        """Research this topic."""
        ...

    assert research_topic.__name__ == "research_topic"
    assert research_topic.__doc__ == "Research this topic."
    assert inspect.signature(research_topic) == inspect.signature(expected)


def test_summon_registers_pydantic_input_and_output_contracts():
    summon = Summon("svc")

    @summon("/research")
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        ...

    endpoint = summon.endpoints[0]
    assert endpoint.input_model is ResearchRequest
    assert endpoint.output_model is ResearchResponse
    assert endpoint.return_type == "ResearchResponse"


def _register_with_unresolvable_annotations(source: str):
    """Register an endpoint whose annotations cannot be evaluated at runtime."""
    namespace: dict = {}
    # exec keeps the caller's `from __future__ import annotations`, which is what
    # leaves these annotations unevaluated at registration time.
    exec(source, namespace)


def test_summon_rejects_an_unresolvable_parameter_annotation():
    """Silently dropping the contract is what this must never do again."""
    with pytest.raises(TypeError, match="Could not resolve the annotation"):
        _register_with_unresolvable_annotations(
            "from summonpot import Summon\n"
            "summon = Summon('svc')\n"
            "@summon('/research')\n"
            "def research(request: OnlyUnderTypeChecking) -> str:\n"
            "    '''Research a topic.'''\n"
            "    ...\n"
        )


def test_summon_rejects_an_unresolvable_return_annotation():
    with pytest.raises(TypeError, match="the return type"):
        _register_with_unresolvable_annotations(
            "from summonpot import Summon\n"
            "summon = Summon('svc')\n"
            "@summon('/research')\n"
            "def research(query: str) -> MissingResponseModel:\n"
            "    '''Research a topic.'''\n"
            "    ...\n"
        )


def test_summon_rejects_a_model_defined_in_a_local_scope():
    """A model built inside a factory is the realistic way to hit this."""

    def build_pot():
        class LocalRequest(BaseModel):
            query: str

        summon = Summon("svc")

        @summon("/research")
        def research(request: LocalRequest) -> str:
            """Research a topic."""
            ...

        return summon

    with pytest.raises(TypeError, match="Could not resolve the annotation"):
        build_pot()


def test_summon_requires_a_docstring_goal():
    """The docstring is the agent's instructions, so an empty one is not usable."""
    summon = Summon("svc")

    with pytest.raises(TypeError, match="has no docstring"):

        @summon("/research")
        def research(request: ResearchRequest) -> ResearchResponse: ...


def test_summon_rejects_a_whitespace_only_docstring():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="has no docstring"):

        @summon("/research")
        def research(request: ResearchRequest) -> ResearchResponse:
            """ """
            ...


def test_summon_rejects_mixed_pydantic_and_scalar_inputs():
    summon = Summon("svc")

    with pytest.raises(TypeError, match="exactly one request parameter"):

        @summon("/research")
        def research(request: ResearchRequest, trace_id: str) -> ResearchResponse:
            """Research a topic."""
            ...


def test_summon_compiles_dependency_parameters_as_closed_capabilities():
    def load_sources(query: str) -> list[str]:
        """Load sources for the validated query."""
        return [query]

    def rank_sources(sources: list[str]) -> list[str]:
        """Rank the loaded sources."""
        return sources

    summon = Summon("svc")

    @summon("/research")
    def research(
        request: ResearchRequest,
        sources=Depends(load_sources),
        ranking=Required(rank_sources),
    ) -> ResearchResponse:
        """Research a topic using only the declared capabilities."""
        ...

    endpoint = summon.endpoints[0]
    assert endpoint.input_model is ResearchRequest
    assert [parameter.name for parameter in endpoint.parameters] == ["request"]
    assert [tool.name for tool in endpoint.tools] == ["load_sources", "rank_sources"]
    assert [tool.required for tool in endpoint.tools] == [False, True]


def test_summon_rejects_duplicate_capability_names():
    def lookup(query: str) -> str:
        return query

    def second_lookup(query: str) -> str:
        return query

    second_lookup.__name__ = "lookup"
    summon = Summon("svc")

    with pytest.raises(TypeError, match="Duplicate capability name: lookup"):

        @summon("/research")
        def research(
            request: ResearchRequest,
            first=Depends(lookup),
            second=Depends(second_lookup),
        ) -> ResearchResponse:
            """Research a topic."""
            ...


def test_application_level_tools_shared_across_endpoints():
    summon = Summon("svc", tools=[search_web_raw])

    @summon("/one")
    def one(q: str) -> str:
        """One."""
        return ""

    @summon("/two")
    def two(q: str) -> str:
        """Two."""
        return ""

    assert len(summon.endpoints[0].tools) == 1
    assert len(summon.endpoints[1].tools) == 1
    assert summon.endpoints[0].tools[0].name == "search_web_raw"


def test_endpoint_specific_tools_merged():
    summon = Summon("svc", tools=[search_web_raw])

    @summon("/custom", tools=[translate_raw])
    def custom(q: str) -> str:
        """Custom."""
        return ""

    names = [t.name for t in summon.endpoints[0].tools]
    assert names == ["search_web_raw", "translate_raw"]


def test_tool_decorator_builds_tooldef():
    @tool(name="my_tool", description="Does a thing")
    def some_func(x: int) -> int:
        """Ignored — description override wins."""
        return x

    assert some_func.name == "my_tool"
    assert some_func.description == "Does a thing"
    assert some_func.parameters[0].name == "x"
    assert some_func.parameters[0].type_annotation == "int"


def test_repr():
    summon = Summon("svc")

    @summon("/x")
    def x() -> str:
        """X."""
        return ""

    assert "endpoints=1" in repr(summon)


# --- helpers (plain functions, not decorated) ---


def search_web_raw(query: str) -> list[dict]:
    """Search the web for information."""
    return []


def translate_raw(text: str, target: str = "es") -> str:
    """Translate text to a target language."""
    return text


def test_summon_accepts_explicitly_quoted_forward_references():
    """`request: "ResearchRequest"` is a valid annotation and must not be rejected.

    Under PEP 563 the stored source is `'"ResearchRequest"'`, so evaluating it once
    yields the string `'ResearchRequest'` rather than the class.
    """
    summon = Summon("svc")

    @summon("/research")
    def research(request: "ResearchRequest") -> "ResearchResponse":  # noqa: UP037
        """Research a topic."""
        ...

    endpoint = summon.endpoints[0]
    assert endpoint.input_model is ResearchRequest
    assert endpoint.output_model is ResearchResponse


def test_summon_still_rejects_a_quoted_name_that_does_not_exist():
    with pytest.raises(TypeError, match="'StillMissing'"):
        _register_with_unresolvable_annotations(
            "from summonpot import Summon\n"
            "summon = Summon('svc')\n"
            "@summon('/research')\n"
            'def research(request: "StillMissing") -> str:\n'
            "    '''Research a topic.'''\n"
            "    ...\n"
        )


def test_summon_resolves_forward_references_inside_container_annotations():
    """`list["ResearchResponse"]` must resolve, not stay a container of strings."""
    summon = Summon("svc")

    @summon("/research")
    def research(request: "ResearchRequest") -> "ResearchResponse":  # noqa: UP037
        """Research a topic."""
        ...

    @summon("/batch")
    def batch(items: list["ResearchRequest"]) -> dict[str, "ResearchResponse"]:  # noqa: UP037
        """Research several topics."""
        ...

    assert summon.endpoints[0].input_model is ResearchRequest
    # The container resolved to real classes, so it renders with their names rather
    # than as a container of quoted strings.
    batch_endpoint = summon.endpoints[1]
    assert batch_endpoint.parameters[0].type_annotation == "list[ResearchRequest]"
    assert batch_endpoint.return_type == "dict[str, ResearchResponse]"


def test_summon_rejects_a_missing_name_nested_in_a_container():
    with pytest.raises(TypeError, match="'MissingInside'"):
        _register_with_unresolvable_annotations(
            "from summonpot import Summon\n"
            "summon = Summon('svc')\n"
            "@summon('/research')\n"
            'def research(items: list["MissingInside"]) -> str:\n'
            "    '''Research topics.'''\n"
            "    ...\n"
        )


def test_summon_rejects_a_path_without_a_leading_slash():
    """Such a path registers and builds, but no request can ever reach it."""
    summon = Summon("svc")

    with pytest.raises(ValueError, match="must start with '/'"):

        @summon("research")
        def research(request: ResearchRequest) -> ResearchResponse:
            """Research a topic."""
            ...


def test_summon_rejects_a_duplicate_path():
    """Starlette dispatches the first match, so the second was silently dead."""
    summon = Summon("svc")

    @summon("/research")
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        ...

    with pytest.raises(ValueError, match="POST /research is already registered"):

        @summon("/research")
        def research_again(request: ResearchRequest) -> ResearchResponse:
            """Research a topic differently."""
            ...

    assert len(summon.endpoints) == 1


def test_summon_allows_one_path_to_carry_different_methods():
    """GET /orders and POST /orders are distinct routes."""
    summon = Summon("svc")

    @summon("/orders", method="GET")
    def list_orders(status: str = "open") -> str:
        """List orders."""
        return ""

    @summon("/orders", method="POST")
    def place_order(item: str) -> str:
        """Place an order."""
        return ""

    assert len(summon.endpoints) == 2


def test_summon_normalizes_the_method_when_detecting_duplicates():
    summon = Summon("svc")

    @summon("/orders", method="GET")
    def list_orders(status: str = "open") -> str:
        """List orders."""
        return ""

    with pytest.raises(ValueError, match="GET /orders is already registered"):

        @summon("/orders", method="get")
        def list_orders_again(status: str = "open") -> str:
            """List orders again."""
            return ""


def test_summon_rejects_unimplemented_streaming():
    """The flag shipped in 0.2.0 but was never read by the runtime or the server."""
    summon = Summon("svc")

    with pytest.raises(NotImplementedError, match="stream=True is not implemented"):

        @summon("/research", stream=True)
        def research(request: ResearchRequest) -> ResearchResponse:
            """Research a topic."""
            ...

    assert summon.endpoints == []


def test_summon_still_accepts_the_default_non_streaming_endpoint():
    summon = Summon("svc")

    @summon("/research")
    def research(request: ResearchRequest) -> ResearchResponse:
        """Research a topic."""
        ...

    assert summon.endpoints[0].stream is False


def test_application_level_capabilities_are_not_shared_between_endpoints():
    """`required` is per-endpoint state and must not leak across endpoints."""
    summon = Summon("svc", tools=[search_web_raw])

    @summon("/one")
    def one(q: str) -> str:
        """One."""
        return ""

    @summon("/two")
    def two(q: str) -> str:
        """Two."""
        return ""

    first, second = summon.endpoints[0].tools[0], summon.endpoints[1].tools[0]
    assert first is not second
    assert first is not summon._tools[0]

    first.required = True

    assert second.required is False
    assert summon._tools[0].required is False


def test_summon_accepts_a_default_model():
    summon = Summon("svc", model="anthropic:claude-sonnet-4-5")

    assert summon._runtime.default_model == "anthropic:claude-sonnet-4-5"


def test_summon_rejects_both_model_and_runtime():
    """A supplied runtime already carries its own model."""
    from summonpot.runtime import Runtime

    with pytest.raises(TypeError, match="not both"):
        Summon("svc", model="openai:gpt-4o-mini", runtime=Runtime())


def test_summon_normalizes_and_records_the_method():
    summon = Summon("svc")

    @summon("/forecast", method="get")
    def forecast(city: str) -> str:
        """Report the forecast."""
        return ""

    assert summon.endpoints[0].method == "GET"


def test_summon_rejects_an_unsupported_method():
    summon = Summon("svc")

    with pytest.raises(ValueError, match="Unsupported HTTP method"):

        @summon("/forecast", method="TRACE")
        def forecast(city: str) -> str:
            """Report the forecast."""
            return ""


def test_summon_rejects_a_request_model_on_a_bodyless_method():
    """A GET has no body to carry the model, so this must fail at registration."""
    summon = Summon("svc")

    with pytest.raises(TypeError, match="carries no request body"):

        @summon("/research", method="GET")
        def research(request: ResearchRequest) -> ResearchResponse:
            """Research a topic."""
            ...


@pytest.mark.parametrize(
    "annotation",
    ["dict[str, int] | None", "dict[str, int]", "ResearchRequest | None"],
)
def test_summon_rejects_query_annotations_with_no_encoding(annotation):
    """These used to reach FastAPI and crash build_app() during startup."""
    namespace = {"ResearchRequest": ResearchRequest, "Summon": Summon}
    source = (
        f"def endpoint(payload: {annotation} = None) -> str:\n"
        "    '''Look something up.'''\n"
        "    return ''\n"
    )
    exec(source, namespace)
    summon = Summon("svc")

    with pytest.raises(TypeError, match="has no query encoding"):
        summon("/lookup", method="GET")(namespace["endpoint"])


@pytest.mark.parametrize("annotation", ["list[int] | None", "int | str", "str"])
def test_summon_accepts_query_representable_annotations(annotation):
    namespace = {"Summon": Summon}
    source = (
        f"def endpoint(value: {annotation} = None) -> str:\n"
        "    '''Look something up.'''\n"
        "    return ''\n"
    )
    exec(source, namespace)
    summon = Summon("svc")

    summon("/lookup", method="GET")(namespace["endpoint"])

    assert summon.endpoints[0].method == "GET"


@pytest.mark.parametrize(
    "annotation",
    [
        "Literal['open', 'closed']",
        "list[Literal['open', 'closed']] | None",
        "Annotated[str, Field(min_length=3)]",
        "Annotated[list[int], Field()] | None",
    ],
)
def test_summon_accepts_constrained_scalar_query_annotations(annotation):
    """Literal and Annotated wrap a scalar; they do not make it unrepresentable."""
    namespace = {
        "Annotated": Annotated,
        "Literal": Literal,
        "Field": Field,
        "Summon": Summon,
    }
    source = (
        f"def endpoint(value: {annotation} = None) -> str:\n"
        "    '''Look something up.'''\n"
        "    return ''\n"
    )
    exec(source, namespace)
    summon = Summon("svc")

    summon("/lookup", method="GET")(namespace["endpoint"])

    assert summon.endpoints[0].method == "GET"


def test_summon_still_rejects_a_mapping_hidden_behind_annotated():
    """Unwrapping Annotated must not open a hole for mappings."""
    namespace = {"Annotated": Annotated, "Field": Field, "Summon": Summon}
    source = (
        "def endpoint(value: Annotated[dict[str, int], Field()] = None) -> str:\n"
        "    '''Look something up.'''\n"
        "    return ''\n"
    )
    exec(source, namespace)
    summon = Summon("svc")

    with pytest.raises(TypeError, match="has no query encoding"):
        summon("/lookup", method="GET")(namespace["endpoint"])


def test_summon_rejects_the_same_path_and_method_twice():
    summon = Summon("svc")

    @summon("/orders", method="GET")
    def list_orders(status: str = "open") -> str:
        """List orders."""
        return ""

    with pytest.raises(ValueError, match="GET /orders is already registered"):

        @summon("/orders", method="get")
        def list_orders_again(status: str = "open") -> str:
            """List orders differently."""
            return ""

    assert len(summon.endpoints) == 1


def test_summon_accepts_a_local_model_passed_as_a_live_annotation():
    """A function-scoped model resolves when the annotation is the class itself.

    Only a postponed or quoted annotation has to look the name up again, which is
    what fails when the defining scope is gone.
    """
    source = (
        "from pydantic import BaseModel\n"
        "from summonpot import Summon\n"
        "def build():\n"
        "    class LocalRequest(BaseModel):\n"
        "        query: str\n"
        "    summon = Summon('svc')\n"
        "    @summon('/research')\n"
        "    def research(request: LocalRequest) -> str:\n"
        '        """Research a topic."""\n'
        "        ...\n"
        "    return summon\n"
    )
    # dont_inherit: this module uses postponed annotations, and exec would
    # otherwise pass that flag on -- the very condition being excluded here.
    namespace: dict = {}
    exec(compile(source, "<local-model>", "exec", dont_inherit=True), namespace)

    summon = namespace["build"]()

    assert summon.endpoints[0].input_model.__name__ == "LocalRequest"


# --- #78: path parameters are declared, validated and owned by the URL -------


def test_path_placeholders_become_path_parameters():
    summon = Summon("app")

    @summon.summon("/customers/{customer_id}", method="POST")
    def update_customer(customer_id: str, name: str) -> str:
        """Update one customer."""
        ...

    assert summon.endpoints[0].path_parameter_names == ("customer_id",)


def test_a_route_without_placeholders_owns_no_path_parameters():
    summon = Summon("app")

    @summon.summon("/customers", method="POST")
    def create_customer(name: str) -> str:
        """Create one customer."""
        ...

    assert summon.endpoints[0].path_parameter_names == ()


def test_several_placeholders_keep_route_order():
    summon = Summon("app")

    @summon.summon("/orgs/{org_id}/customers/{customer_id}", method="PUT")
    def move_customer(org_id: str, customer_id: str, name: str) -> str:
        """Move a customer."""
        ...

    assert summon.endpoints[0].path_parameter_names == ("org_id", "customer_id")


def test_a_placeholder_with_no_matching_parameter_is_rejected():
    summon = Summon("app")

    with pytest.raises(ValueError, match="has no parameter named"):

        @summon.summon("/customers/{customer_id}", method="POST")
        def update_customer(name: str) -> str:
            """No customer_id in the signature."""
            ...


def test_a_repeated_placeholder_is_rejected():
    summon = Summon("app")

    with pytest.raises(ValueError, match="more than once"):

        @summon.summon("/customers/{customer_id}/{customer_id}", method="POST")
        def update_customer(customer_id: str, name: str) -> str:
            """Named twice."""
            ...


def test_an_optional_path_parameter_is_rejected():
    """A URL segment is always present, so a default could never apply."""
    summon = Summon("app")

    with pytest.raises(ValueError, match="declared optional"):

        @summon.summon("/customers/{customer_id}", method="POST")
        def update_customer(customer_id: str = "x", name: str = "y") -> str:
            """Optional path parameter."""
            ...


def test_a_non_scalar_path_parameter_is_rejected():
    """A path segment is text; a list has no unambiguous reading from one."""
    summon = Summon("app")

    with pytest.raises(ValueError, match="must be scalars"):

        @summon.summon("/customers/{customer_id}", method="POST")
        def update_customer(customer_id: list[str], name: str) -> str:
            """Structured path parameter."""
            ...


@pytest.mark.parametrize("annotation", [str, int, float, bool, UUID])
def test_every_supported_scalar_is_accepted(annotation):
    summon = Summon("app")

    def update_customer(customer_id: annotation, name: str) -> str:  # type: ignore[valid-type]
        """Update one customer."""
        ...

    update_customer.__annotations__["customer_id"] = annotation
    summon.summon("/customers/{customer_id}", method="POST")(update_customer)

    assert summon.endpoints[0].path_parameter_names == ("customer_id",)


def test_bodyless_methods_are_unaffected():
    """GET already bound placeholders through the query-handler signature."""
    summon = Summon("app")

    @summon.summon("/customers/{customer_id}", method="GET")
    def get_customer(customer_id: str) -> str:
        """Read one customer."""
        ...

    assert summon.endpoints[0].path_parameter_names == ("customer_id",)
