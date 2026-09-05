"""The Summon application object."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import replace
from enum import Enum
from functools import wraps
from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel

from summonpot._annotations import (
    get_type_str,
    reject_unresolved,
    safe_get_type_hints,
    type_name,
)
from summonpot._execution import _register_endpoint
from summonpot._validation import validate_contracts
from summonpot.dependencies import Dependency
from summonpot.models import (
    EndpointDef,
    ParamDef,
    ToolDef,
    operation_id_for,
    path_placeholders,
)
from summonpot.runtime import Runtime
from summonpot.tools import build_tool_from_func

_PATH_SCALARS: tuple[type, ...] = (str, int, float, bool, UUID)


def _is_path_scalar(parameter: ParamDef) -> bool:
    """Whether a declared parameter can be carried in a URL segment.

    A path segment is text. str/int/float/bool/UUID have an unambiguous reading
    from one; a list or a model does not, and inventing an encoding here would
    be a transport API this issue explicitly does not add.
    """
    annotation = getattr(parameter, "annotation", None)
    if annotation is None:
        # Fall back to the display string for parameters declared without a
        # resolved annotation.
        return parameter.type_annotation in {"str", "int", "float", "bool", "UUID"}
    annotation = _unwrap_annotated(annotation)
    return isinstance(annotation, type) and issubclass(annotation, _PATH_SCALARS)


class Summon:
    """A contract-first application containing declared endpoints.

    Example::

        from pydantic import BaseModel
        from summonpot import Summon

        class ResearchRequest(BaseModel):
            query: str

        class ResearchResponse(BaseModel):
            summary: str

        summon = Summon(tools=[search_web])

        @summon("/research")
        def research_topic(request: ResearchRequest) -> ResearchResponse:
            \"\"\"Research this topic thoroughly.\"\"\"
            ...

        summon.serve()
    """

    def __init__(
        self,
        name: str | None = None,
        tools: list | None = None,
        *,
        model: str | None = None,
        runtime: Runtime | None = None,
    ) -> None:
        """Create a Summon application.

        Args:
            name: Service name, used as the OpenAPI title.
            tools: Capabilities available to every endpoint.
            model: Default model for every endpoint, overriding ``SUMMONPOT_MODEL``.
            runtime: A configured runtime. Supply one to bound what a single call
                may spend, via ``Runtime(usage_limits=..., timeout=...)``. A runtime
                already carries its own model, so this is mutually exclusive with
                ``model``.
        """
        if runtime is not None and model is not None:
            raise TypeError(
                "Pass either model= or runtime=, not both. Set the model on the "
                "runtime you supply instead."
            )
        self.name = name or "summonpot"
        # Convert any raw functions to ToolDef objects
        self._tools: list = []
        if tools:
            for t in tools:
                if isinstance(t, ToolDef):
                    self._tools.append(t)
                else:
                    self._tools.append(build_tool_from_func(t))
        self._endpoints: list[EndpointDef] = []
        # (path, method) -> endpoint name, for duplicate-route detection.
        self._routes: dict[tuple[str, str], str] = {}
        # operation_id -> endpoint name. Distinct routes can still collide here:
        # the id is derived from the declared name, and two endpoints may share
        # a name while sitting on different paths.
        self._operation_ids: dict[str, str] = {}
        self._runtime = runtime if runtime is not None else Runtime(model=model)

    def __repr__(self) -> str:
        return f"Summon({self.name!r}, endpoints={len(self._endpoints)}, tools={len(self._tools)})"

    def __call__(
        self,
        path: str,
        *,
        tools: list | None = None,
        stream: bool = False,
        model: str | None = None,
        method: str = "POST",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Declare an endpoint at the given route.

        Args:
            path: URL path for the endpoint (e.g. ``/research``).
            tools: Additional tools specific to this endpoint.
            stream: Not implemented. Passing ``True`` raises, rather than
                silently returning a fully buffered response.
            model: LLM model override for this endpoint.
            method: HTTP method (default POST). Bodyless methods (GET, DELETE,
                HEAD) take their parameters as a query string.
        """
        normalized_method = method.upper()
        if normalized_method not in SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported HTTP method {method!r}. Supported methods are "
                f"{', '.join(sorted(SUPPORTED_METHODS))}."
            )

        if stream:
            raise NotImplementedError(
                "stream=True is not implemented. The flag shipped in 0.2.0 but was "
                "never read, so a streaming endpoint returned a fully buffered "
                "response with no indication the flag did nothing. Omit it until "
                "streaming lands."
            )

        if not path.startswith("/"):
            raise ValueError(
                f"Endpoint path {path!r} must start with '/'. A path without a "
                "leading slash registers an endpoint that no request can reach."
            )

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            endpoint_name = func.__name__
            description = inspect.getdoc(func) or ""
            if not description.strip():
                # The docstring is the endpoint's goal, not documentation. Without
                # it the agent is given an empty system prompt and told nothing
                # about what the endpoint is for.
                raise TypeError(
                    f"Endpoint {endpoint_name!r} has no docstring. The docstring is "
                    "the endpoint's goal and becomes the agent's instructions, so "
                    "it is required."
                )

            # Merge application-level tools with endpoint-specific tools. Each endpoint
            # gets its own ToolDef: `required` is per-endpoint state, so sharing
            # one object would let a Required(...) on one endpoint leak into every
            # other endpoint using the same capability.
            all_tools = [replace(t) for t in self._tools]
            if tools:
                # Convert raw functions to ToolDefs
                for t in tools:
                    if not isinstance(t, ToolDef):
                        all_tools.append(build_tool_from_func(t))
                    else:
                        all_tools.append(replace(t))

            # Extract parameters from function signature
            sig = inspect.signature(func)
            hints = safe_get_type_hints(func)
            parameters: list[ParamDef] = []
            dependency_tools: list[ToolDef] = []
            input_model: type[BaseModel] | None = None
            for pname, param in sig.parameters.items():
                if pname in ("self", "cls"):
                    continue
                if isinstance(param.default, Dependency):
                    # `.callable` unwraps an Operation contract; a bare callable
                    # passes through unchanged, so existing endpoints are untouched.
                    dependency_tool = build_tool_from_func(param.default.callable)
                    dependency_tool.required = param.default.required
                    dependency_tool.contract = param.default.contract
                    dependency_tool.bounds = param.default.bounds
                    dependency_tools.append(dependency_tool)
                    continue
                annotation = hints.get(pname, param.annotation)
                reject_unresolved(
                    annotation, where=f"parameter {pname!r}", endpoint=endpoint_name
                )
                if _is_pydantic_model(annotation):
                    input_model = annotation
                type_str = get_type_str(pname, param, hints)
                is_required = param.default is inspect.Parameter.empty
                parameters.append(
                    ParamDef(
                        name=pname,
                        type_annotation=type_str,
                        description="",
                        required=is_required,
                        default=None if is_required else param.default,
                        annotation=(
                            None
                            if annotation is inspect.Parameter.empty
                            else annotation
                        ),
                    )
                )

            if input_model is not None and len(parameters) != 1:
                raise TypeError(
                    "Pydantic endpoints must declare exactly one request parameter"
                )

            if input_model is not None and normalized_method in BODYLESS_METHODS:
                raise TypeError(
                    f"Endpoint {endpoint_name!r} uses {normalized_method}, which "
                    "carries no request body, so it cannot take a Pydantic request "
                    "model. Declare the fields as individual parameters, or use "
                    "POST."
                )

            if normalized_method in BODYLESS_METHODS:
                for parameter in parameters:
                    if _is_query_representable(parameter.annotation):
                        continue
                    raise TypeError(
                        f"Endpoint {endpoint_name!r} uses {normalized_method}, so "
                        f"parameter {parameter.name!r} has to travel in the query "
                        f"string, and {parameter.type_annotation!r} has no query "
                        "encoding. Use a scalar or a sequence of scalars, or use "
                        "POST so it can be sent in the request body."
                    )

            # Return type
            return_hint = hints.get("return", sig.return_annotation)
            reject_unresolved(
                return_hint, where="the return type", endpoint=endpoint_name
            )
            output_model = return_hint if _is_pydantic_model(return_hint) else None
            if return_hint is inspect.Parameter.empty or return_hint is None:
                return_type = "str"
            else:
                # Rendered with the shared helper so a generic keeps its arguments;
                # __name__ alone reduces dict[str, Response] to "dict".
                return_type = type_name(return_hint)

            endpoint_tools = [*all_tools, *dependency_tools]
            validate_contracts(
                endpoint=endpoint_name,
                tools=endpoint_tools,
                input_model=input_model,
                parameters=parameters,
            )
            tool_names = [tool.name for tool in endpoint_tools]
            duplicate_names = sorted(
                {name for name in tool_names if tool_names.count(name) > 1}
            )
            if duplicate_names:
                raise TypeError(f"Duplicate capability name: {duplicate_names[0]}")

            # Path parameters (#78). The route template is part of the endpoint
            # contract: a URL identifier and a body identifier of the same name
            # are two sources of truth for one value, and today the body wins
            # silently. Partition the declared scalars here, once, so the
            # transport layer never has to re-derive which side owns what.
            placeholders = path_placeholders(path)
            declared = {p.name: p for p in parameters}
            path_parameter_names: tuple[str, ...] = ()

            if placeholders:
                seen: set[str] = set()
                for placeholder in placeholders:
                    if not placeholder or not placeholder.isidentifier():
                        raise ValueError(
                            f"{path!r} has the placeholder {{{placeholder}}}, which is "
                            "not a valid Python identifier, so no endpoint parameter "
                            "can ever match it."
                        )
                    if placeholder in seen:
                        raise ValueError(
                            f"{path!r} names {{{placeholder}}} more than once. A "
                            "placeholder must match exactly one endpoint parameter."
                        )
                    seen.add(placeholder)

                    matched = declared.get(placeholder)
                    if matched is None:
                        raise ValueError(
                            f"{path!r} declares {{{placeholder}}} but {endpoint_name!r} "
                            f"has no parameter named {placeholder!r}. Add it to the "
                            "signature, or remove it from the route."
                        )
                    if not matched.required:
                        raise ValueError(
                            f"{placeholder!r} is a path parameter of {path!r}, so it is "
                            "always present in the URL, but it is declared optional. "
                            "Remove its default."
                        )
                    if not _is_path_scalar(matched):
                        raise ValueError(
                            f"{placeholder!r} is a path parameter of {path!r} but is "
                            f"annotated {matched.type_annotation!r}. Path parameters "
                            "must be scalars (str, int, float, bool, UUID); a "
                            "structured value belongs in the body."
                        )

                # The issue asks that a Pydantic request-model endpoint with path
                # parameters fail clearly at registration. It already does, and
                # earlier than here: "Pydantic endpoints must declare exactly one
                # request parameter" rejects the mixed signature before this runs.
                # Adding a second check would have been unreachable code asserting
                # a guarantee something else already makes.

                path_parameter_names = tuple(placeholders)

            # Keyed on the pair, not the path alone: GET /orders and POST /orders
            # are different routes, while a second GET /orders would be dispatched
            # to the first and silently become dead code.
            route = (path, normalized_method)
            existing_name = self._routes.get(route)
            if existing_name is not None:
                raise ValueError(
                    f"{normalized_method} {path} is already registered by "
                    f"{existing_name!r}. Only the first registration is reachable, "
                    "so the second would be silently dead code."
                )

            # Checked here rather than at schema-generation time so a collision
            # is a registration error rather than a duplicate-operation warning
            # buried in the OpenAPI output -- and so it can never reach a client
            # generator, which would emit two identically named methods.
            operation_id = operation_id_for(endpoint_name, normalized_method)
            clashing_name = self._operation_ids.get(operation_id)
            if clashing_name is not None:
                raise ValueError(
                    f"{endpoint_name!r} and {clashing_name!r} both produce the "
                    f"OpenAPI operationId {operation_id!r}. Operation ids must be "
                    "unique, so a generated client would have two methods with "
                    "the same name. Rename one of the two endpoints."
                )

            endpoint = EndpointDef(
                path=path,
                name=endpoint_name,
                description=description,
                parameters=parameters,
                return_type=return_type,
                input_model=input_model,
                output_model=output_model,
                tools=endpoint_tools,
                stream=stream,
                model=model,
                method=normalized_method,
                path_parameter_names=path_parameter_names,
                operation_id=operation_id,
            )
            _register_endpoint(endpoint)
            self._routes[route] = endpoint_name
            self._operation_ids[operation_id] = endpoint_name
            self._endpoints.append(endpoint)

            @wraps(func)
            def declaration(*args: Any, **kwargs: Any) -> Any:
                raise TypeError(
                    f"Summonpot endpoint declaration {endpoint_name!r} is not directly "
                    f"callable. Serve the Summon application or invoke "
                    f"{normalized_method} {path}."
                )

            return declaration

        return decorator

    # Temporary source-compatibility bridge for applications that have already renamed
    # `Pot` to `Summon` but still use `summon.summon(...)`. The callable application is
    # the only canonical spelling and the only one taught by first-party examples.
    summon = __call__

    @property
    def endpoints(self) -> list[EndpointDef]:
        """Return all registered endpoints."""
        return list(self._endpoints)

    def serve(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
    ) -> None:
        """Serve endpoints as an HTTP API.

        Starts a FastAPI + uvicorn server.
        Requires the ``serve`` extra: ``pip install summonpot[serve]``

        Warning:
            ``host`` defaults to ``0.0.0.0``, which accepts connections on every
            interface. That suits the container deployments summonpot targets, but
            it is wider than uvicorn's own ``127.0.0.1`` default. Endpoints carry no
            authentication yet and each call spends provider credit, so anything
            reachable from outside your network needs both a bound runtime
            (``Runtime(usage_limits=..., timeout=...)``) and authentication in front
            of it. Pass ``host="127.0.0.1"`` for local development.
        """
        self._serve_api(host, port)

    def _serve_api(self, host: str, port: int) -> None:
        try:
            import uvicorn
        except ImportError:
            raise ModuleNotFoundError(
                "uvicorn and fastapi are required for serving. "
                "Install with: pip install summonpot[serve]"
            ) from None

        from summonpot.server import build_app

        app = build_app(self)
        uvicorn.run(app, host=host, port=port)  # type: ignore[arg-type]


def _unwrap_annotated(annotation: Any) -> Any:
    """Return the underlying type of an ``Annotated``, leaving anything else alone."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _is_query_scalar(annotation: Any) -> bool:
    """Report whether a single value can travel in a query string."""
    annotation = _unwrap_annotated(annotation)
    if annotation is Any:
        return True

    origin = get_origin(annotation)
    if origin is Literal:
        # A constrained scalar: every member still arrives as one query value.
        return all(
            isinstance(member, str | int | float | bool | bytes | Enum)
            or member is None
            for member in get_args(annotation)
        )
    if origin is not None:
        # A nested generic, e.g. dict[str, int] or list[list[int]].
        return False
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return False
    return not (isinstance(annotation, type) and issubclass(annotation, Mapping))


def _is_query_representable(annotation: Any) -> bool:
    """Report whether an annotation can be expressed as a query parameter.

    A query string carries scalars and repeated scalars. Mappings and nested models
    have no agreed encoding, so they belong in a request body.
    """
    if annotation is None or annotation is inspect.Parameter.empty:
        return True

    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        return all(
            _is_query_representable(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    if origin in (list, set, frozenset, tuple):
        return all(
            _is_query_scalar(argument)
            for argument in get_args(annotation)
            if argument is not Ellipsis
        )
    return _is_query_scalar(annotation)


BODYLESS_METHODS = frozenset({"GET", "DELETE", "HEAD"})
SUPPORTED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})


def _is_pydantic_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)
