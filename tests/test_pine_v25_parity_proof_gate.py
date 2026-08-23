from daily_alpha.pine_bar_outcome_compare import BarOutcomeReport
from daily_alpha.pine_parity_compare import ParityReport
from daily_alpha.pine_v25_historical_reference import HistoricalV25Evaluation
from daily_alpha.pine_v25_parity_proof_gate import (
    V25ParityProofGate,
    evaluate_v25_parity_proof_gate,
)


def _report(reference_count: int, *, exact: bool = True) -> ParityReport:
    return ParityReport(
        reference_count=reference_count,
        python_count=reference_count if exact else max(reference_count - 1, 0),
        exact_match_count=reference_count if exact else 0,
        mismatch_count=0 if exact else 1,
        mismatches=(),
    )


def _history(reference_count: int, *, exact: bool = True) -> HistoricalV25Evaluation:
    return HistoricalV25Evaluation(
        reference_id="v25-history",
        parameter_manifest_sha256="b" * 64,
        signal_report=_report(reference_count, exact=exact),
        bar_outcome_report=BarOutcomeReport(
            reference_count=100,
            python_count=100 if exact else 99,
            exact_bar_count=100 if exact else 99,
            mismatch_count=0 if exact else 1,
            mismatches=(),
        ),
    )


def test_v25_missing_evidence_fails_closed() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=None,
        forward_report=None,
        forward_monitor_deployed=False,
    )

    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_PARITY_EVIDENCE_MISSING",
        "FORWARD_PARITY_MONITOR_NOT_DEPLOYED",
        "FORWARD_PARITY_EVIDENCE_MISSING",
    )
    assert gate.promotion_authorized is False
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False


def test_v25_exact_empty_comparisons_are_not_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(0),
        forward_report=_report(0),
        forward_monitor_deployed=True,
    )

    assert gate.historical_parameter_manifest_locked is True
    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_GENUINE_SIGNAL_EVIDENCE_EMPTY",
        "FORWARD_GENUINE_SIGNAL_EVIDENCE_EMPTY",
    )


def test_v25_monitor_deployment_is_required_for_forward_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(3),
        forward_report=_report(2),
        forward_monitor_deployed=False,
    )

    assert gate.parity_evidence_complete is False
    assert gate.blockers == ("FORWARD_PARITY_MONITOR_NOT_DEPLOYED",)


def test_v25_exact_nonempty_evidence_completes_only_the_evidence_gate() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(4),
        forward_report=_report(2),
        forward_monitor_deployed=True,
    )

    assert gate.parity_evidence_complete is True
    assert gate.blockers == ()
    assert gate.historical_reference_signal_count == 4
    assert gate.forward_reference_signal_count == 2
    assert gate.promotion_authorized is False
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False


def test_v25_proof_record_cannot_smuggle_promotion_authority() -> None:
    try:
        V25ParityProofGate(
            historical_exact=True,
            historical_reference_signal_count=1,
            historical_parameter_manifest_locked=True,
            forward_exact=True,
            forward_reference_signal_count=1,
            forward_monitor_deployed=True,
            blockers=(),
            parity_evidence_complete=True,
            promotion_authorized=True,
        )
    except ValueError as exc:
        assert str(exc) == "parity proof gate cannot authorize promotion"
    else:
        raise AssertionError("promotion authority must fail closed")
