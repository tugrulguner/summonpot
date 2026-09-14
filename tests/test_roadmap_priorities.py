"""Pin planned safety prerequisites without claiming they already execute."""

import re
from pathlib import Path

ROADMAP = Path(__file__).resolve().parents[1] / "ROADMAP.md"


def test_hardening_is_planned_and_precedes_execution_expansion():
    text = ROADMAP.read_text(encoding="utf-8")
    planned = text.split("## Next milestones", 1)[1].split("## Non-goals", 1)[0]
    headings = re.findall(r"^### (\d+)\. (.+)$", planned, re.MULTILINE)
    assert [int(number) for number, _ in headings] == list(range(1, 10))
    assert headings[0][1] == "Contract enforcement and input/output hardening"
    assert "planned acceptance criteria, not claims" in planned

    hardening = " ".join(planned.split("### 2.", 1)[0].split())
    for requirement in (
        "reject the unsupported declaration before serving",
        "Adding a second capability must not remove enforcement",
        "invalid source rejection",
        "unsupported runtime call-bound rejection",
        "receiving operation constraints",
        "render model input only when agent execution needs it",
        "duplicate JSON keys",
        "sensitive validation inputs, provider bodies, or exception chains",
        "a copy-hook fix alone is not completion of the transport boundary",
    ):
        assert requirement in hardening


def test_count_type_validation_is_shipped_not_future_runtime_enforcement():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    shipped, planned = text.split("## Next milestones", 1)
    hardening = planned.split("### 2.", 1)[0]
    for requirement in (
        "Construction-time validation in `CallBounds`, `Exactly`, `AtLeast`, `AtMost`, and `Between`",
        "non-negative built-in integer counts",
        "excluding booleans, fractions, and non-finite values",
        "does not imply broader runtime call-bound enforcement",
    ):
        assert requirement in shipped
        assert requirement not in hardening
    assert "Construction-time count-type validation is already shipped" in hardening
    assert "broader runtime enforcement follows in milestone 5" in hardening
    assert "invalid source/count rejection" not in planned


def test_raw_runtime_input_parity_is_unreleased_not_part_of_080_history():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    shipped = text.split("## Shipped foundation", 1)[1].split("### 0.5.0 boundary", 1)[
        0
    ]
    released_080 = text.split("### 0.8.0 boundary", 1)[1].split(
        "### Unreleased / next release boundary", 1
    )[0]
    unreleased = text.split("### Unreleased / next release boundary", 1)[1].split(
        "## Next milestones", 1
    )[0]

    for behavior in (
        "Raw runtime mappings use the declared request contract",
        "Parameterless endpoints compile an explicit empty raw contract",
    ):
        assert behavior not in released_080
        assert behavior in unreleased
    assert "Matching raw `Runtime.call` input validation" not in shipped


def test_context_slices_require_their_actual_execution_prerequisites():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    basic = text.split("#### A1.", 1)[1].split("#### A2.", 1)[0]
    results = text.split("#### A2.", 1)[1].split("### B.", 1)[0]
    assert "After milestone 1's boundary hardening" in basic
    assert "without waiting for milestones 2\N{EN DASH}3" in basic
    assert "Budget the complete model request" in basic
    assert "Keep canonical request state and the invocation ledger separate" in basic
    assert "Defer result eviction and result-backed summarization to A2" in basic
    assert (
        "Only after validated result chains and producer-constrained choices (milestones 2\N{EN DASH}3)"
        in results
    )
    for requirement in (
        "scoped retrieval of declared operation results",
        "preserve exact canonical values for `FromResult` and producer-constrained choices",
        "recover an evicted tool result",
        "compaction summaries non-authoritative",
        "recovery of omitted evidence",
    ):
        assert requirement in results
        assert requirement not in basic


def test_chain_failure_semantics_are_not_deferred_to_adapters():
    text = ROADMAP.read_text(encoding="utf-8")
    chain = " ".join(text.split("### 2.", 1)[1].split("### 3.", 1)[0].split())
    for requirement in (
        "Failure semantics ship with the chain",
        "partial completion",
        "uncertain outcome after timeout",
        "final-output retries must not replay effects",
        "Required use alone does not prove",
        "Preserve application-provided idempotency keys",
        "Execution remains sequential initially",
    ):
        assert requirement in chain


def test_agent_context_track_preserves_declarative_authority():
    text = ROADMAP.read_text(encoding="utf-8")
    track = " ".join(
        text.split("## Agent execution and context track", 1)[1]
        .split("## Non-goals", 1)[0]
        .split()
    )
    for requirement in (
        "endpoint body remains `...`",
        "not yet shipped Summonpot features",
        "After milestone 1's boundary hardening",
        "Only after authenticated application context (milestone 4)",
        "Keep stateless requests the default",
        "compaction summaries non-authoritative",
        "Search does not add capabilities",
        "Charge child and summarizer work to the same parent budget",
        "model judges may supplement semantic-quality evaluation",
        "No claimed performance gain ships without measured evidence",
    ):
        assert requirement in track
