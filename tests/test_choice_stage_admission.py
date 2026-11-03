"""The new composition admits only one producer-backed prefix choice."""

from typing import Literal

import pytest
from test_choice_stage import Candidate, Report, Request, Selected, Snapshot

from summonpot import (
    AgentChoice,
    Between,
    Exactly,
    FromRequest,
    FromResult,
    Operation,
    Required,
    Summon,
)


def declare(kind):
    def find(category: str) -> list[Candidate]:
        return [Candidate(identifier=category)]

    def select(candidate: Candidate, other: Candidate | None = None) -> Selected:
        return Selected(identifier=candidate.identifier)

    def select_again(candidate: Candidate) -> Selected:
        return Selected(identifier=candidate.identifier)

    def inspect(
        identifier: str,
        check: Literal["stock", "prices"],
        candidate: Candidate | None = None,
    ) -> Snapshot:
        return Snapshot(identifier=identifier, check=check)

    def finish(identifier: str, check: str) -> Report:
        return Report(identifier=identifier, check=check)

    producer = Operation(
        find, bind={"category": FromRequest("category")}, output=list[Candidate]
    )
    selection_bind = {"candidate": AgentChoice(from_result=producer)}
    if kind == "two-arguments":
        selection_bind["other"] = AgentChoice(from_result=producer)
    selected = Operation(select, bind=selection_bind, output=Selected)
    again = Operation(
        select_again,
        bind={"candidate": AgentChoice(from_result=producer)},
        after=(selected,),
        output=Selected,
    )
    stage_bind = {
        "identifier": FromResult(
            again if kind == "two-frontiers" else selected, "identifier"
        ),
        "check": AgentChoice(),
    }
    if kind == "inside-stage":
        stage_bind["candidate"] = AgentChoice(from_result=producer)
    repeated = Operation(inspect, bind=stage_bind, output=Snapshot)
    if kind == "after-stage":
        repeated = Operation(
            inspect,
            bind={"identifier": FromRequest("category"), "check": AgentChoice()},
            after=(producer,),
            output=Snapshot,
        )
        selected = Operation(
            select, bind=selection_bind, after=(repeated,), output=Selected
        )
    final_bind = {
        "identifier": FromResult(selected, "identifier")
        if kind == "after-stage"
        else FromResult(repeated, "identifier", invocation="final"),
        "check": FromResult(repeated, "check", invocation="final"),
    }
    final = Operation(finish, bind=final_bind, output=Report)
    operations = (
        [producer, selected]
        + ([again] if kind == "two-frontiers" else [])
        + [repeated, final]
    )
    app = Summon("narrow-composition")
    if kind == "two-frontiers":

        @app("/review")
        def five(
            request: Request,
            a=Required(operations[0], calls=Exactly(1)),
            b=Required(operations[1], calls=Exactly(1)),
            c=Required(operations[2], calls=Exactly(1)),
            d=Required(operations[3], calls=Between(1, 3)),
            e=Required(operations[4], calls=Exactly(1)),
        ) -> Report:
            """Select an eligible item, inspect stock and prices and return a report."""
            ...
    else:

        @app("/review")
        def four(
            request: Request,
            a=Required(operations[0], calls=Exactly(1)),
            b=Required(operations[1], calls=Exactly(1)),
            c=Required(operations[2], calls=Between(1, 3)),
            d=Required(operations[3], calls=Exactly(1)),
        ) -> Report:
            """Select an eligible item, inspect stock and prices and return a report."""
            ...

    return app


@pytest.mark.parametrize(
    "kind", ["two-arguments", "two-frontiers", "inside-stage", "after-stage"]
)
def test_additional_choice_shapes_are_rejected_before_serving(kind):
    with pytest.raises(TypeError):
        declare(kind)
