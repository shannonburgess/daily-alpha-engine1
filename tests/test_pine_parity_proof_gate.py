from daily_alpha.pine_bar_outcome_compare import BarOutcomeReport
from daily_alpha.pine_historical_reference import HistoricalV24Evaluation
from daily_alpha.pine_parity_compare import ParityReport
from daily_alpha.pine_parity_proof_gate import (
    V24ParityProofGate,
    evaluate_v24_parity_proof_gate,
)


def _parity_report(reference_count: int, *, exact: bool = True) -> ParityReport:
    return ParityReport(
        reference_count=reference_count,
        python_count=reference_count if exact else max(reference_count - 1, 0),
        exact_match_count=reference_count if exact else 0,
        mismatch_count=0 if exact else 1,
        mismatches=(),
    )


def _historical_evaluation(
    reference_signal_count: int,
    *,
    exact: bool = True,
) -> HistoricalV24Evaluation:
    return HistoricalV24Evaluation(
        reference_id="historical-reference-v1",
        signal_report=_parity_report(reference_signal_count, exact=exact),
        bar_outcome_report=BarOutcomeReport(
            reference_count=100,
            python_count=100 if exact else 99,
            exact_bar_count=100 if exact else 99,
            mismatch_count=0 if exact else 1,
            mismatches=(),
        ),
    )


def test_missing_evidence_fails_closed() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=None,
        forward_report=None,
        forward_monitor_deployed=False,
    )

    assert gate.parity_evidence_complete is False
    assert gate.promotion_authorized is False
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False
    assert gate.blockers == (
        "HISTORICAL_PARITY_EVIDENCE_MISSING",
        "FORWARD_PARITY_MONITOR_NOT_DEPLOYED",
        "FORWARD_PARITY_EVIDENCE_MISSING",
    )


def test_exact_zero_signal_comparisons_are_not_parity_proof() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(0),
        forward_report=_parity_report(0),
        forward_monitor_deployed=True,
    )

    assert gate.historical_exact is True
    assert gate.forward_exact is True
    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_GENUINE_SIGNAL_EVIDENCE_EMPTY",
        "FORWARD_GENUINE_SIGNAL_EVIDENCE_EMPTY",
    )


def test_forward_monitor_runtime_proof_is_required_even_with_exact_events() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(3),
        forward_report=_parity_report(2),
        forward_monitor_deployed=False,
    )

    assert gate.parity_evidence_complete is False
    assert gate.blockers == ("FORWARD_PARITY_MONITOR_NOT_DEPLOYED",)


def test_mismatch_blocks_evidence_completion_without_retuning() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(3, exact=False),
        forward_report=_parity_report(2, exact=False),
        forward_monitor_deployed=True,
    )

    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_PARITY_MISMATCH",
        "FORWARD_PARITY_MISMATCH",
    )


def test_nonempty_exact_historical_and_forward_evidence_complete_the_gate() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(4),
        forward_report=_parity_report(2),
        forward_monitor_deployed=True,
    )

    assert gate.parity_evidence_complete is True
    assert gate.blockers == ()
    assert gate.historical_reference_signal_count == 4
    assert gate.forward_reference_signal_count == 2
    assert gate.promotion_authorized is False
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False


def test_proof_record_itself_cannot_smuggle_promotion_authority() -> None:
    try:
        V24ParityProofGate(
            historical_exact=True,
            historical_reference_signal_count=1,
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
