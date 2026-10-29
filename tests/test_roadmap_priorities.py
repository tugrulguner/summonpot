"""Pin planned safety prerequisites without claiming they already execute."""

import re
from pathlib import Path

ROADMAP = Path(__file__).resolve().parents[1] / "ROADMAP.md"


def test_v010_boundary_completes_milestone_one_before_execution_expansion():
    text = ROADMAP.read_text(encoding="utf-8")
    shipped = " ".join(text.split("## Next milestones", 1)[0].split())
    planned = text.split("## Next milestones", 1)[1].split("## Non-goals", 1)[0]
    headings = re.findall(r"^### (\d+)\. (.+)$", planned, re.MULTILINE)
    assert [int(number) for number, _ in headings] == list(range(1, 8))
    assert headings[0][1] == "Contract enforcement and input/output hardening"
    assert "planned acceptance criteria, not claims" in planned

    hardening = " ".join(planned.split("### 2.", 1)[0].split())
    for completed in (
        "receiving operation constraints",
        "render model input only when agent execution needs it",
        "a copy-hook fix alone is not completion of the transport boundary",
    ):
        assert completed not in hardening
    for completed in (
        "Receiving-operation constraint validation is shipped",
        "Fail-closed runtime admission",
        "Structural output-namespace validation",
        "Raw runtime mappings use the declared request contract",
    ):
        assert completed in shipped
    v090 = shipped.split("0.9.0 boundary", 1)[1].split("0.10.0 boundary", 1)[0]
    v010 = shipped.split("0.10.0 boundary", 1)[1]
    assert "did not ship stable failure-boundary handling" in v090
    assert "did not ship" in v090 and "runtime deadline" in v090
    for shipped_contract in (
        "stable redacted failure responses",
        "one monotonic runtime deadline",
        "HTTP body parsing, request validation, and response serialization are outside that deadline",
        "cannot be preempted",
        "does not prove that an effect did not occur",
    ):
        assert shipped_contract in v010
    assert "No remaining acceptance criteria are listed" in hardening
    assert "Finish the remaining deadline contract" not in hardening


def test_output_namespace_hardening_is_shipped_not_planned():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    shipped, planned = text.split("## Next milestones", 1)

    for requirement in (
        "Structural output-namespace validation",
        "duplicate field, alias, serialization-alias, and computed-field JSON keys",
        "allowed extras that shadow canonical field names or emitted aliases",
        "retaining noncolliding validated extras",
    ):
        assert requirement in shipped
        assert requirement not in planned


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
    assert "unsupported runtime bounds fail before serving" not in hardening
    assert "### 4. Broader private execution compiler" in planned
    assert "invalid source/count rejection" not in planned


def test_fail_closed_admission_is_shipped_not_left_as_a_future_claim():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    shipped, planned = text.split("## Next milestones", 1)
    hardening = planned.split("### 2.", 1)[0]

    assert "Fail-closed runtime admission" in shipped
    assert "All other explicit shapes fail before serving" in shipped
    assert "The admission gate is shipped" not in hardening
    assert "second-capability regression" not in hardening
    assert "invalid source rejection" not in hardening
    assert "unsupported runtime call-bound rejection" not in hardening


def test_v090_boundary_records_the_completed_hardening_release():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    shipped = text.split("## Shipped foundation", 1)[1].split("### 0.5.0 boundary", 1)[
        0
    ]
    released_080 = text.split("### 0.8.0 boundary", 1)[1].split(
        "### 0.9.0 boundary", 1
    )[0]
    released_090 = text.split("### 0.9.0 boundary", 1)[1].split(
        "## Next milestones", 1
    )[0]

    for behavior in (
        "fail-closed runtime admission",
        "receiving operation constraints",
        "output namespaces",
        "Raw runtime mappings use the declared request contract",
        "Parameterless endpoints compile an explicit empty raw contract",
    ):
        assert behavior not in released_080
        assert behavior in released_090
    assert "Matching raw `Runtime.call` input validation" not in shipped
    assert "### Unreleased / next release boundary" not in text
    assert "### Unreleased boundary: model-free resolved chains" not in text


def test_context_slices_require_their_actual_execution_prerequisites():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    basic = text.split("#### A1.", 1)[1].split("#### A2.", 1)[0]
    results = text.split("#### A2.", 1)[1].split("### B.", 1)[0]
    assert "authenticated application context still requires milestone 4" not in text
    assert (
        "authenticated application context is already available under the 0.13.0 boundary above"
        in results
    )
    assert "With milestone 1's boundary hardening now complete in 0.10.0" in basic
    assert "without waiting for milestones 2\N{EN DASH}3" in basic
    assert "Budget the complete model request" in basic
    assert "Keep canonical request state and the invocation ledger separate" in basic
    assert "Defer result eviction and result-backed summarization to A2" in basic
    assert "Only after broader orchestration (milestone 3)" in results
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
    orchestration = " ".join(text.split("### 3.", 1)[1].split("### 4.", 1)[0].split())
    for requirement in (
        "validated successes and starts respectively",
        "retain reservations for failed, cancelled, or uncertain starts",
        "Model retries cannot replay an effect",
        "one unambiguous terminal operation/result",
        "partial completion and timeout uncertainty",
    ):
        assert requirement in orchestration


def test_future_execution_milestones_follow_the_approved_dependency_order():
    text = ROADMAP.read_text(encoding="utf-8")
    planned = text.split("## Next milestones", 1)[1].split(
        "## Agent execution and context track", 1
    )[0]
    headings = re.findall(r"^### (\d+)\. (.+)$", planned, re.MULTILINE)
    assert [int(number) for number, _ in headings] == list(range(1, 8))
    names = [name for _, name in headings]
    assert names[1:] == [
        "Result-dependent execution with one producer-backed choice",
        "Bounded orchestration with multiple choices and repeated calls",
        "Broader private execution compiler",
        "Exact bounded database operations and transaction boundaries",
        "Concrete recovery and long-running execution",
        "Optional execution harnesses",
    ]


def test_initial_result_dependent_execution_acceptance_is_explicit():
    text = " ".join(ROADMAP.read_text(encoding="utf-8").split())
    initial = text.split(
        "### 2. Result-dependent execution with one producer-backed choice", 1
    )[1].split("### 3.", 1)[0]
    for requirement in (
        "Completed in 0.14.0",
        "existing uniquely ordered chain of at least two required `Exactly(1)` operations",
        "exactly one producer-backed choice argument",
        "before model resolution",
        "no candidates",
        "without resolving or constructing a model",
        "multiple candidates",
        "same endpoint/provider",
        "all other admitted declarations keep their existing agent-mediated route",
        "token forgery",
        "cannot authorize or replay effects",
    ):
        assert requirement in initial
    assert "historical v0.11.0, v0.12.0, or v0.13.0 boundaries" in initial
    assert (
        "published v0.13.0 chains with producer-backed choices remain agent-mediated"
        in initial
    )


def test_historical_release_boundaries_are_retained_and_not_retroactively_broadened():
    text = ROADMAP.read_text(encoding="utf-8")
    shipped = text.split("## Next milestones", 1)[0]
    for boundary in (
        "0.5.0",
        "0.6.0",
        "0.7.0",
        "0.8.0",
        "0.9.0",
        "0.10.0",
        "0.11.0",
        "0.12.0",
        "0.13.0",
    ):
        assert f"### {boundary} boundary" in shipped
    assert (
        "### 0.14.0 boundary: result-dependent execution with one producer-backed choice"
        in shipped
    )
    assert "Historical v0.11.0 chains remain agent-mediated." in shipped
    assert (
        "Any `AgentChoice`, including producer-backed choices, keeps the chain agent-mediated."
        in shipped
    )
    assert "Historical 0.12.0 does not include authenticated context." in shipped


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
        "With milestone 1's boundary hardening now complete in 0.10.0",
        "Only after authenticated application context is available (included from 0.13.0)",
        "Keep stateless requests the default",
        "compaction summaries non-authoritative",
        "Search does not add capabilities",
        "Charge child and summarizer work to the same parent budget",
        "model judges may supplement semantic-quality evaluation",
        "No claimed performance gain ships without measured evidence",
    ):
        assert requirement in track
