"""HTTP server for summonpot — builds FastAPI routes from endpoints."""

from __future__ import annotations

import inspect
import logging
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Any, Union, get_args, get_origin

from summonpot import __version__
from summonpot._execution import _RequestValues
from summonpot.summon import BODYLESS_METHODS, _unwrap_annotated

if TYPE_CHECKING:
    from summonpot.summon import Summon

logger = logging.getLogger("summonpot.server")


def build_app(summon: Summon) -> Any:
    """Build a FastAPI application from a Summon instance."""
    from fastapi import FastAPI

    app = FastAPI(
        title=summon.name,
        description=(
            "A contract-first Python framework for modernizing APIs for AI through exact "
            "application behavior and explicitly bounded agent-owned decisions."
        ),
        version=__version__,
    )

    for endpoint in summon.endpoints:
        route_path = endpoint.path
        method = endpoint.method

        if endpoint.parameters and method in BODYLESS_METHODS:
            # GET/DELETE/HEAD carry no request body, so the declared parameters
            # become query parameters instead.
            _handle_with_query = _make_query_handler(endpoint, summon)
            app.add_api_route(
                route_path,
                _handle_with_query,
                methods=[method],
                response_model=endpoint.output_model,
                summary=(
                    endpoint.description.split("\n")[0]
                    if endpoint.description
                    else endpoint.name
                ),
                description=endpoint.description,
            )
        elif endpoint.parameters:
            RequestModel: Any
            if endpoint.input_model is not None:
                RequestModel = endpoint.input_model
            elif not _body_parameters(endpoint):
                # Every declared parameter is carried by the URL, so there is no
                # body left to describe. Generating an empty model anyway would
                # make the body *required*: FastAPI answers a bodyless
                # `POST /items/{item_id}` with 422 and never reaches the runtime,
                # even though the URL already supplied every value.
                RequestModel = None
            else:
                from pydantic import create_model

                fields: dict[str, tuple[type, Any]] = {}
                for p in _body_parameters(endpoint):
                    field_type = _field_type(p)
                    if p.required:
                        fields[p.name] = (field_type, ...)
                    else:
                        fields[p.name] = (field_type, p.default)

                RequestModel = create_model(
                    f"{endpoint.name}Request",
                    **fields,  # pyright: ignore[reportArgumentType, reportCallIssue]
                )

            _handle_with_body = _make_body_handler(endpoint, summon, RequestModel)

            app.add_api_route(
                route_path,
                _handle_with_body,
                methods=[method],
                response_model=endpoint.output_model,
                summary=(
                    endpoint.description.split("\n")[0]
                    if endpoint.description
                    else endpoint.name
                ),
                description=endpoint.description,
            )
        else:
            _handle_without_body = _make_no_body_handler(endpoint, summon)

            app.add_api_route(
                route_path,
                _handle_without_body,
                methods=[method],
                response_model=endpoint.output_model,
                summary=(
                    endpoint.description.split("\n")[0]
                    if endpoint.description
                    else endpoint.name
                ),
                description=endpoint.description,
            )

    return app


async def _run_endpoint(summon: Any, endpoint: Any, params: dict[str, Any]) -> Any:
    """Run an endpoint, translating runtime failures into stable HTTP responses.

    Without this every failure — an unmet required capability, a provider outage, an
    exhausted budget — reached the caller as an indistinguishable bare 500.
    """
    from fastapi import HTTPException
    from pydantic_ai.exceptions import (
        ModelHTTPError,
        UnexpectedModelBehavior,
        UsageLimitExceeded,
        UserError,
    )

    try:
        return await summon._runtime.call(endpoint, params)
    except UsageLimitExceeded as exc:
        # Details are logged, never returned: an exception raised inside the agent
        # loop can carry rejected model output or tool-call context, and the HTTP
        # response is the one surface an untrusted caller reads.
        logger.warning(
            "Endpoint %s exceeded its usage limit", endpoint.path, exc_info=exc
        )
        raise HTTPException(
            status_code=429,
            detail="Endpoint exceeded its configured usage limit.",
        ) from exc
    except TimeoutError as exc:
        logger.warning("Endpoint %s timed out", endpoint.path, exc_info=exc)
        raise HTTPException(
            status_code=504,
            detail="Endpoint timed out before the model produced a valid response.",
        ) from exc
    except ModelHTTPError as exc:
        logger.warning(
            "Endpoint %s failed against the model provider", endpoint.path, exc_info=exc
        )
        # A provider rate limit is the one upstream status a caller can act on.
        status_code = 429 if exc.status_code == 429 else 502
        raise HTTPException(
            status_code=status_code,
            detail=f"Model provider request failed with status {exc.status_code}.",
        ) from exc
    except UserError as exc:
        # The provider rejected its own configuration - almost always a missing or
        # wrong API key. That is an operator problem, not a caller problem, so the
        # guidance goes to the log and the caller gets a stable 500.
        logger.error(
            "Endpoint %s is not configured; the model provider rejected the "
            "configuration. This is usually a missing API key for the selected "
            "model. Set SUMMONPOT_MODEL=test to run without a provider account.",
            endpoint.path,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Endpoint is not configured. See the server logs.",
        ) from exc
    except UnexpectedModelBehavior as exc:
        logger.warning(
            "Endpoint %s did not satisfy its contract", endpoint.path, exc_info=exc
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Model did not satisfy the endpoint contract within the retry budget."
            ),
        ) from exc


def _body_parameters(endpoint: Any) -> list[Any]:
    """The declared parameters the JSON body owns.

    Path parameters are excluded: the URL is the single authority for them, and
    leaving them in the generated model would put the same value in two places
    with the body silently winning.
    """
    owned = set(getattr(endpoint, "path_parameter_names", ()) or ())
    return [p for p in endpoint.parameters if p.name not in owned]


def _path_parameters(endpoint: Any) -> list[Any]:
    """The declared parameters bound from the URL, in route order."""
    by_name = {p.name: p for p in endpoint.parameters}
    return [
        by_name[name]
        for name in getattr(endpoint, "path_parameter_names", ()) or ()
        if name in by_name
    ]


def _make_body_handler(
    endpoint: Any, summon: Any, request_model: type[Any] | None
) -> Any:
    """Create a route handler for a body method, retaining endpoint context in its closure.

    `request_model` is None when the URL owns every declared parameter. The
    handler then takes no body argument at all, so the route stays callable
    with nothing but its path segments.
    """

    path_parameters = _path_parameters(endpoint)

    # The synthetic body parameter shares one namespace with the path
    # parameters, and the path parameter names come from the URL, so `body` is
    # not ours to reserve. A route as ordinary as `/items/{body}` put two
    # parameters called `body` into the signature below and `build_app()` died
    # with `ValueError: duplicate parameter name: 'body'` -- the whole
    # application refusing to start over a legal declaration. Step aside until
    # the name is free; the prefix cannot collide in turn, because each
    # candidate is re-checked.
    body_name = "body"
    taken = {p.name for p in path_parameters}
    while body_name in taken:
        body_name = f"_{body_name}"

    # Everything arrives by keyword so that the body can be looked up under
    # whichever name was free. Binding it positionally would mean the name in
    # `__signature__` and the name FastAPI calls with could drift apart.
    async def handle(**values: Any) -> Any:
        path_values = dict(values)
        body = path_values.pop(body_name, None)

        if hasattr(body, "model_dump"):
            prompt = body.model_dump(mode="json", by_alias=True)
            typed = {name: getattr(body, name) for name in type(body).model_fields}
        else:
            prompt = dict(body or {})
            typed = dict(prompt)

        # The URL wins, and nothing it owns was ever in the body model, so
        # there is nothing here to overwrite -- this adds, it does not resolve a
        # conflict. Both views are kept: `typed` carries the value FastAPI
        # validated (an int stays an int, a UUID stays a UUID), while `prompt`
        # carries a JSON-safe rendering for the model prompt.
        for name, value in path_values.items():
            typed[name] = value
            prompt[name] = (
                value if isinstance(value, (str, int, float, bool)) else str(value)
            )

        return await _run_endpoint(
            summon, endpoint, _RequestValues(prompt, typed=typed)
        )

    # FastAPI reads __signature__, so naming the path parameters explicitly is
    # what turns them into bound, validated, documented path parameters instead
    # of an undocumented **kwargs. Same technique as _make_query_handler.
    # It is set even when there are no path parameters: without it FastAPI
    # inspects the real signature, sees `**values`, and tries to bind it.
    parameters = []
    annotations: dict[str, Any] = {}
    if request_model is not None:
        parameters.append(
            inspect.Parameter(
                body_name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=request_model,
            )
        )
        annotations[body_name] = request_model
    for p in path_parameters:
        annotation = _field_type(p)
        parameters.append(
            inspect.Parameter(
                p.name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation
            )
        )
        annotations[p.name] = annotation

    handle.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    handle.__annotations__ = annotations
    return handle


def _needs_query_marker(annotation: Any) -> bool:
    """Report whether FastAPI needs an explicit Query marker to bind this type."""
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        return any(
            _needs_query_marker(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    return origin in (list, set, frozenset, tuple)


def _make_query_handler(endpoint: Any, summon: Any) -> Any:
    """Create a handler whose parameters arrive as a query string."""

    from fastapi import Query

    async def handle(**kwargs: Any) -> Any:
        return await _run_endpoint(summon, endpoint, kwargs)

    parameters = []
    annotations: dict[str, Any] = {}
    for p in endpoint.parameters:
        # Same resolved annotation the body path uses, so a union stays nullable and
        # a generic keeps its element type instead of collapsing to its first member.
        annotation = _field_type(p)
        # A sequence is read as a request body unless it is marked as a query
        # parameter, so it would silently arrive as None on a bodyless method. The
        # marker goes *inside* Annotated rather than into the default: as a default
        # it replaces whatever FieldInfo the annotation already carried, silently
        # dropping the declared constraint.
        if _needs_query_marker(annotation):
            annotation = Annotated[annotation, Query()]

        default = inspect.Parameter.empty if p.required else p.default

        parameters.append(
            inspect.Parameter(
                p.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
        annotations[p.name] = annotation

    # FastAPI reads __signature__, so this is what turns **kwargs into a documented
    # set of query parameters.
    handle.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    handle.__annotations__ = annotations
    return handle


def _make_no_body_handler(endpoint: Any, summon: Any) -> Any:
    """Create a parameter-free route handler with context retained in its closure."""

    async def handle() -> Any:
        return await _run_endpoint(summon, endpoint, {})

    return handle


def _field_type(param: Any) -> Any:
    """Resolve the request-body field type for one endpoint parameter.

    Prefers the resolved annotation object so unions stay nullable, ``Any`` stays
    permissive, and a generic keeps its element type. Falls back to parsing the
    display string only when no annotation could be resolved.
    """
    annotation = param.annotation
    if annotation is None or isinstance(annotation, str):
        return _str_to_type(param.type_annotation)
    return annotation


def _str_to_type(type_str: str) -> type:
    """Convert a type annotation string to a Python type.

    Fallback for parameters whose annotation could not be resolved to an object.
    """
    mapping: dict[str, type] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "Any": str,
        "None": type(None),
    }
    base = type_str.split("[")[0].split("|")[0].strip()
    return mapping.get(base, str)
