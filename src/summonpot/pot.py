"""Pot — the summoning vessel. Register endpoints, summon agents."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from summonpot.models import EndpointDef, ParamDef, ToolDef
from summonpot.runtime import Runtime
from summonpot.tools import build_tool_from_func


class Pot:
    """A summoning vessel for agentic endpoints.

    Example::

        from pydantic import BaseModel
        from summonpot import Pot

        class ResearchRequest(BaseModel):
            query: str

        class ResearchResponse(BaseModel):
            summary: str

        pot = Pot(tools=[search_web])

        @pot.summon("/research")
        def research_topic(request: ResearchRequest) -> ResearchResponse:
            \"\"\"Research this topic thoroughly.\"\"\"
            raise NotImplementedError

        pot.serve()
    """

    def __init__(
        self,
        name: str | None = None,
        tools: list | None = None,
    ) -> None:
        self.name = name or "summonpot"
        # Convert any raw functions to ToolDef objects
        self._pot_tools: list = []
        if tools:
            for t in tools:
                if isinstance(t, ToolDef):
                    self._pot_tools.append(t)
                else:
                    self._pot_tools.append(build_tool_from_func(t))
        self._endpoints: list[EndpointDef] = []
        self._runtime = Runtime()

    def __repr__(self) -> str:
        return f"Pot({self.name!r}, endpoints={len(self._endpoints)}, tools={len(self._pot_tools)})"

    def summon(
        self,
        path: str,
        *,
        tools: list | None = None,
        stream: bool = False,
        model: str | None = None,
        method: str = "POST",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator: summon an agent behind the given route.

        Args:
            path: URL path for the endpoint (e.g. ``/research``).
            tools: Additional tools specific to this endpoint.
            stream: Whether to stream the response.
            model: LLM model override for this endpoint.
            method: HTTP method (default POST).
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            endpoint_name = func.__name__
            description = inspect.getdoc(func) or ""

            # Merge pot-level tools with endpoint-specific tools
            all_tools = list(self._pot_tools)
            if tools:
                # Convert raw functions to ToolDefs
                for t in tools:
                    if not isinstance(t, ToolDef):
                        all_tools.append(build_tool_from_func(t))
                    else:
                        all_tools.append(t)

            # Extract parameters from function signature
            sig = inspect.signature(func)
            hints = _safe_get_type_hints(func)
            parameters: list[ParamDef] = []
            input_model: type[BaseModel] | None = None
            for pname, param in sig.parameters.items():
                if pname in ("self", "cls"):
                    continue
                annotation = hints.get(pname, param.annotation)
                if _is_pydantic_model(annotation):
                    input_model = annotation
                type_str = _get_type_str(pname, param, hints)
                is_required = param.default is inspect.Parameter.empty
                parameters.append(
                    ParamDef(
                        name=pname,
                        type_annotation=type_str,
                        description="",
                        required=is_required,
                        default=None if is_required else param.default,
                    )
                )

            if input_model is not None and len(parameters) != 1:
                raise TypeError(
                    "Pydantic endpoints must declare exactly one request parameter"
                )

            # Return type
            return_hint = hints.get("return", sig.return_annotation)
            output_model = return_hint if _is_pydantic_model(return_hint) else None
            if return_hint is inspect.Parameter.empty or return_hint is None:
                return_type = "str"
            elif hasattr(return_hint, "__name__"):
                return_type = return_hint.__name__
            else:
                return_type = str(return_hint)

            endpoint = EndpointDef(
                path=path,
                name=endpoint_name,
                description=description,
                parameters=parameters,
                return_type=return_type,
                input_model=input_model,
                output_model=output_model,
                tools=all_tools,
                stream=stream,
                model=model,
            )
            self._endpoints.append(endpoint)
            return func

        return decorator

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


def _is_pydantic_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _get_type_str(
    pname: str,
    param: inspect.Parameter,
    hints: dict[str, Any],
) -> str:
    if pname in hints:
        return _type_name(hints[pname])
    if param.annotation is not inspect.Parameter.empty:
        return _type_name(param.annotation)
    return "str"


def _type_name(tp: Any) -> str:
    if hasattr(tp, "__origin__"):
        origin = tp.__origin__
        args = tp.__args__
        if origin is list and args:
            return f"list[{_type_name(args[0])}]"
        if origin is dict and len(args) >= 2:
            return f"dict[{_type_name(args[0])}, {_type_name(args[1])}]"
        if origin is tuple:
            return f"tuple[{', '.join(_type_name(a) for a in args)}]"
        return _type_name(origin)
    if tp is type(None):
        return "None"
    if hasattr(tp, "__name__"):
        return tp.__name__
    return str(tp)


def _safe_get_type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return inspect.get_annotations(func, eval_str=True)
    except Exception:
        return inspect.get_annotations(func, eval_str=False)
