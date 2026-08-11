"""HTTP server for summonpot — builds FastAPI routes from endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from summonpot import __version__

if TYPE_CHECKING:
    from summonpot.pot import Pot


def build_app(pot: Pot) -> Any:
    """Build a FastAPI application from a Pot instance."""
    from fastapi import FastAPI

    app = FastAPI(
        title=pot.name,
        description="An AI-native API framework. Every endpoint is an agent that runs automatically.",
        version=__version__,
    )

    for endpoint in pot.endpoints:
        route_path = endpoint.path
        method = "POST"

        if endpoint.parameters:
            from pydantic import create_model

            fields: dict[str, tuple[type, Any]] = {}
            for p in endpoint.parameters:
                field_type = _str_to_type(p.type_annotation)
                if p.required:
                    fields[p.name] = (field_type, ...)
                else:
                    fields[p.name] = (field_type, p.default)

            RequestModel = create_model(
                f"{endpoint.name}Request",
                **fields,  # pyright: ignore[reportArgumentType, reportCallIssue]
            )

            # Use a unique module-level attribute so FastAPI/Pydantic can resolve it
            import sys as _sys

            _attr = f"_RouteModel_{id(RequestModel)}"
            setattr(_sys.modules[__name__], _attr, RequestModel)

            # Resolve the model for the closure
            resolved_model = RequestModel

            async def _handle_with_body(
                body: resolved_model,  # type: ignore[valid-type]
                _ep=endpoint,
                _pt=pot,
            ) -> Any:
                params = body.model_dump() if hasattr(body, "model_dump") else body
                return await _pt._runtime.call(_ep, params)

            _handle_with_body.__annotations__["body"] = resolved_model

            app.add_api_route(
                route_path,
                _handle_with_body,
                methods=[method],
                summary=(
                    endpoint.description.split("\n")[0]
                    if endpoint.description
                    else endpoint.name
                ),
                description=endpoint.description,
            )
        else:

            async def _handle_without_body(ep=endpoint, pt=pot) -> Any:
                return await pt._runtime.call(ep, {})

            app.add_api_route(
                route_path,
                _handle_without_body,
                methods=[method],
                summary=(
                    endpoint.description.split("\n")[0]
                    if endpoint.description
                    else endpoint.name
                ),
                description=endpoint.description,
            )

    return app


def _str_to_type(type_str: str) -> type:
    """Convert a type annotation string to a Python type."""
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
