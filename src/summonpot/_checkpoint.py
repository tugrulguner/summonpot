"""Private structural admission for bounded checkpoint regions."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, TypeAdapter

from summonpot.contracts import AgentChoice, FromContext, FromRequest, FromResult


@dataclass(frozen=True, slots=True)
class _CheckpointPlan:
    prefix: tuple[int, ...]
    continuation: tuple[int, ...]
    check: int
    terminal: int
    field: str
    rounds: int


def _checkpoint_plan(tools: Sequence[Any]) -> _CheckpointPlan | None:
    marked = [i for i, tool in enumerate(tools) if tool.until is not None]
    if not marked:
        return None
    if len(marked) != 1:
        raise TypeError(
            "Checkpoint declarations require exactly one completion marker."
        )
    check = marked[0]
    field = tools[check].until
    if type(field) is not str or not field:
        raise TypeError(
            "Checkpoint completion must name a canonical stored strict Boolean field."
        )
    identities = {id(t.contract): i for i, t in enumerate(tools)}
    if len(identities) != len(tools) or any(
        t.contract is None
        or t.contract.bind is None
        or t.contract.output is None
        or t.bounds is None
        for t in tools
    ):
        raise TypeError(
            "Checkpoint operations require distinct complete typed contracts and bounds."
        )
    if not tools[check].required:
        raise TypeError("Checkpoint completion must mark a required operation.")
    schema: Any = TypeAdapter(tools[check].contract.output).core_schema
    if schema.get("type") != "model" or schema["schema"].get("type") != "model-fields":
        raise TypeError("Checkpoint output must be a concrete Pydantic model.")
    node = schema["schema"]["fields"].get(field, {}).get("schema", {})
    if node.get("type") != "bool" or node.get("strict") is not True:
        raise TypeError(
            "Checkpoint completion must name a stored strict Boolean field."
        )
    rounds = tools[check].bounds.maximum
    if type(rounds) is not int or rounds < 2:
        raise TypeError("Checkpoint requires finite bounds with at least two checks.")
    terminals = [
        i
        for i, t in enumerate(tools)
        if t.required and (t.bounds.minimum, t.bounds.maximum) == (1, 1)
    ]
    if len(terminals) != 1:
        raise TypeError("Checkpoint requires one exactly-once terminal.")
    terminal = terminals[0]
    prefix = {i for i, t in enumerate(tools) if t.required and i != terminal}
    continuation = set(range(len(tools))) - prefix - {terminal}
    if not continuation:
        raise TypeError("Checkpoint requires a bounded conditional continuation.")
    predecessors: dict[int, set[int]] = {i: set() for i in range(len(tools))}
    saw_request = False
    saw_final = False
    for i, t in enumerate(tools):
        expected = (
            (1, 1)
            if i == terminal
            else ((1, rounds) if i in prefix else (0, rounds - 1))
        )
        if (t.bounds.minimum, t.bounds.maximum) != expected:
            raise TypeError("Checkpoint region bounds must match the check limit.")
        refs = list(t.contract.after)
        arguments = {p.name: p.annotation for p in t.parameters}
        for name, source in t.contract.bind.items():
            if type(source) is FromRequest:
                saw_request |= i in prefix
            elif type(source) is FromContext:
                pass
            elif type(source) is FromResult:
                refs.append(source.operation)
                if i == terminal:
                    if (
                        source.operation is not tools[check].contract
                        or source.invocation != "final"
                    ):
                        raise TypeError(
                            "Checkpoint terminal must read only final checkpoint results."
                        )
                    saw_final = True
                elif source.invocation is not None:
                    raise TypeError("Open checkpoint rounds cannot read final results.")
            elif type(source) is AgentChoice and i in continuation:
                if source.from_result is not None:
                    refs.append(source.from_result)
                else:
                    annotation = arguments[name]
                    if (
                        get_origin(annotation) is not Literal
                        or not get_args(annotation)
                        or any(type(x) is not str for x in get_args(annotation))
                    ):
                        raise TypeError(
                            "Direct checkpoint choices require closed string Literals."
                        )
            else:
                raise TypeError("Unsupported checkpoint argument source.")
        for producer in refs:
            if id(producer) not in identities:
                raise TypeError("Checkpoint references an undeclared producer.")
            predecessors[i].add(identities[id(producer)])
        if i in prefix and not predecessors[i] <= prefix:
            raise TypeError("Checkpoint prefix cannot read continuation results.")
        if i in continuation and terminal in predecessors[i]:
            raise TypeError(
                "Checkpoint continuation cannot depend on terminal results."
            )
        if i == terminal and predecessors[i] != {check}:
            raise TypeError(
                "Checkpoint terminal cannot depend on skipped continuation."
            )
        output = t.contract.output
        if i in prefix and (
            not isinstance(output, type) or not issubclass(output, BaseModel)
        ):
            raise TypeError("Checkpoint prefix requires Pydantic intermediate outputs.")
    if not saw_request or not saw_final:
        raise TypeError(
            "Checkpoint requires request binding and closed terminal result binding."
        )

    def ordered(region: set[int]) -> tuple[int, ...]:
        pending = set(region)
        result = []
        while pending:
            ready = [i for i in pending if not predecessors[i] & pending]
            if len(ready) != 1:
                raise TypeError("Checkpoint regions must have a unique acyclic order.")
            result.append(ready[0])
            pending.remove(ready[0])
        return tuple(result)

    before = ordered(prefix)
    after = ordered(continuation)
    if before[-1] != check:
        raise TypeError("Marked checkpoint must end the required region.")
    reachable = {check}
    for i in after:
        if not predecessors[i] & reachable:
            raise TypeError("Checkpoint continuation must depend on the current check.")
        reachable.add(i)
    return _CheckpointPlan(before, after, check, terminal, field, rounds)
