"""Complete omitted operation outputs before admission, without mutating declarations."""

import inspect
from dataclasses import replace
from typing import Any

from summonpot._annotations import reject_unresolved, safe_get_type_hints
from summonpot.contracts import AgentChoice, FromResult, Operation
from summonpot.models import ToolDef
from summonpot.tools import _annotation_source


def _complete_operation_outputs(tools: list[ToolDef]) -> None:
    contracts = {tool.contract for tool in tools if tool.contract is not None}
    if not any(op.output is None for op in contracts):
        return
    resolved: dict[Operation, Operation] = {}
    pending = set(contracts)
    while pending:
        progressed = False
        for op in tuple(pending):
            refs = set(op.after)
            for source in (op.bind or {}).values():
                if type(source) is FromResult:
                    refs.add(source.operation)
                elif type(source) is AgentChoice and source.from_result is not None:
                    refs.add(source.from_result)
            if refs & pending:
                continue
            output = op.output
            if output is None:
                hints = safe_get_type_hints(_annotation_source(op.operation))
                output = hints.get(
                    "return", inspect.signature(op.operation).return_annotation
                )
                if (
                    output is inspect.Signature.empty
                    or output is Any
                    or output is None
                    or output is type(None)
                ):
                    raise TypeError(
                        "Operation requires an explicit output or a resolved, non-empty return annotation."
                    )
                reject_unresolved(
                    output,
                    where="operation return type",
                    endpoint="operation output inference",
                )
            bindings = None if op.bind is None else dict(op.bind)
            if bindings is not None:
                for name, source in bindings.items():
                    if type(source) is FromResult:
                        bindings[name] = replace(
                            source,
                            operation=resolved.get(source.operation, source.operation),
                        )
                    elif type(source) is AgentChoice and source.from_result is not None:
                        bindings[name] = replace(
                            source,
                            from_result=resolved.get(
                                source.from_result, source.from_result
                            ),
                        )
            after = tuple(resolved.get(ref, ref) for ref in op.after)
            changed = output is not op.output or any(
                resolved.get(ref, ref) is not ref for ref in refs
            )
            resolved[op] = (
                replace(op, output=output, bind=bindings, after=after)
                if changed
                else op
            )
            pending.remove(op)
            progressed = True
        if not progressed:
            raise TypeError(
                "Operation output completion requires acyclic operation references."
            )
    for tool in tools:
        if tool.contract is not None:
            tool.contract = resolved[tool.contract]
