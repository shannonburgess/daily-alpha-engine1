from datetime import UTC, datetime

from daily_alpha.pine_bar_outcome_compare import BarOutcomeReport
from daily_alpha.pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardParityDeploymentEvidence,
    ForwardPersistedEventEvidence,
)
from daily_alpha.pine_forward_reference import (
    PersistedReferenceSnapshot,
    ReceiptBoundForwardParityEvaluation,
)
from daily_alpha.pine_historical_reference import HistoricalV24Evaluation
from daily_alpha.pine_historical_reference_locked import LockedHistoricalV24Evaluation
from daily_alpha.pine_parity_compare import ParityReport, ReferenceSignal
from daily_alpha.pine_parity_proof_gate import (
    V24ParityProofGate,
    evaluate_v24_parity_proof_gate,
)

NOW = datetime(2026, 8, 21, 20, tzinfo=UTC)


def _parity_report(reference_count: int, *, exact: bool = True) -> ParityReport:
    return ParityReport(
        reference_count=reference_count,
        python_count=reference_count if exact else max(reference_count - 1, 0),
        exact_match_count=reference_count if exact else 0,
        mismatch_count=0 if exact else 1,
        mismatches=(),
    )


def _bar_report(*, exact: bool = True) -> BarOutcomeReport:
    return BarOutcomeReport(
        reference_count=100,
        python_count=100 if exact else 99,
        exact_bar_count=100 if exact else 99,
        mismatch_count=0 if exact else 1,
        mismatches=(),
    )


def _historical_evaluation(
    reference_signal_count: int, *, exact: bool = True
) -> LockedHistoricalV24Evaluation:
    return LockedHistoricalV24Evaluation(
        reference_id="historical-reference-v1",
        parameter_manifest_sha256="a" * 64,
        signal_report=_parity_report(reference_signal_count, exact=exact),
        bar_outcome_report=_bar_report(exact=exact),
    )


def _unlocked_historical_evaluation(reference_signal_count: int) -> HistoricalV24Evaluation:
    return HistoricalV24Evaluation(
        reference_id="unlocked-history",
        signal_report=_parity_report(reference_signal_count),
        bar_outcome_report=_bar_report(),
    )


def _persisted_event(index: int) -> ForwardPersistedEventEvidence:
    signal_id = f"SH24-EVENT-{index}"
    fields = {
        "signal_id": signal_id,
        "symbol": f"DINO{index}",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "model_id": "PAPER_SHADOW_V24",
        "timeframe": "1D",
        "price": 97.32 + index,
        "bar_time": NOW.isoformat(),
        "entry_type": "NORMAL_BREAKOUT",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V24",
        signal_id=signal_id,
        fields=tuple(sorted(fields.items())),
    )


def _book(account_id: str, count: int = 0) -> ForwardParityBookEvidence:
    events = tuple(_persisted_event(index) for index in range(count)) if account_id.endswith("V24") else ()
    return ForwardParityBookEvidence(
        account_id=account_id,
        event_count_visible=len(events),
        event_count_scanned=len(events),
        event_history_omitted=0,
        event_limit=100,
        scan_pages=1,
        scan_items_evaluated=len(events),
        open_count=0,
        armed_count_visible=0,
        events=events,
    )


def _deployment_evidence(count: int = 0) -> ForwardParityDeploymentEvidence:
    return ForwardParityDeploymentEvidence(
        repository="shannonburgess/daily-alpha-engine1",
        commit_sha="b" * 40,
        workflow_run_id="32650000000",
        workflow_run_attempt="1",
        processor_version="42",
        processor_code_sha256="code-hash",
        sh24=_book("PAPER_SHADOW_V24", count),
        sh25=_book("PAPER_SHADOW_V25"),
    )


def _forward_evaluation(
    count: int, *, exact: bool = True, commit_sha: str = "b" * 40
) -> ReceiptBoundForwardParityEvaluation:
    signals = tuple(
        ReferenceSignal(
            symbol=f"DINO{index}",
            bar_time=NOW,
            action="ENTRY_LONG",
            price=97.32 + index,
            entry_type="NORMAL_BREAKOUT",
            runner_stage=None,
            quantity_units=None,
            source="TRADINGVIEW_PINE",
            source_id=f"SH24-EVENT-{index}",
        )
        for index in range(count)
    )
    return ReceiptBoundForwardParityEvaluation(
        model_id="PAPER_SHADOW_V24",
        strategy_version="2.4",
        deployment_commit_sha=commit_sha,
        processor_code_sha256="code-hash",
        reference_snapshot=PersistedReferenceSnapshot(
            model_id="PAPER_SHADOW_V24",
            strategy_version="2.4",
            event_count_visible=count,
            event_limit=100,
            scan_items_evaluated=count,
            signals=signals,
        ),
        report=_parity_report(count, exact=exact),
    )


def test_missing_evidence_fails_closed() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=None,
        forward_evaluation=None,
        forward_deployment_evidence=None,
    )
    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_PARITY_EVIDENCE_MISSING",
        "FORWARD_PARITY_MONITOR_DEPLOYMENT_EVIDENCE_MISSING",
        "FORWARD_PARITY_EVIDENCE_MISSING",
    )


def test_exact_zero_signal_comparisons_are_not_parity_proof() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(0),
        forward_evaluation=_forward_evaluation(0),
        forward_deployment_evidence=_deployment_evidence(0),
    )
    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_GENUINE_SIGNAL_EVIDENCE_EMPTY",
        "FORWARD_GENUINE_SIGNAL_EVIDENCE_EMPTY",
    )


def test_unlocked_history_cannot_complete_the_proof_gate() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_unlocked_historical_evaluation(3),
        forward_evaluation=_forward_evaluation(2),
        forward_deployment_evidence=_deployment_evidence(2),
    )
    assert gate.parity_evidence_complete is False
    assert gate.blockers == ("HISTORICAL_PARAMETER_MANIFEST_NOT_LOCKED",)


def test_forward_monitor_runtime_proof_is_required_even_with_exact_events() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(3),
        forward_evaluation=_forward_evaluation(2),
        forward_deployment_evidence=None,
    )
    assert gate.parity_evidence_complete is False
    assert "FORWARD_PARITY_MONITOR_DEPLOYMENT_EVIDENCE_MISSING" in gate.blockers
    assert "FORWARD_PARITY_EVALUATION_NOT_DEPLOYMENT_BOUND" in gate.blockers


def test_mismatch_blocks_evidence_completion_without_retuning() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(3, exact=False),
        forward_evaluation=_forward_evaluation(2, exact=False),
        forward_deployment_evidence=_deployment_evidence(2),
    )
    assert gate.parity_evidence_complete is False
    assert gate.blockers == ("HISTORICAL_PARITY_MISMATCH", "FORWARD_PARITY_MISMATCH")


def test_receipt_identity_or_event_count_mismatch_blocks_forward_proof() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(3),
        forward_evaluation=_forward_evaluation(1, commit_sha="c" * 40),
        forward_deployment_evidence=_deployment_evidence(2),
    )
    assert "FORWARD_PARITY_DEPLOYMENT_COMMIT_MISMATCH" in gate.blockers
    assert "FORWARD_PARITY_RECEIPT_EVENT_COUNT_MISMATCH" in gate.blockers
    assert gate.parity_evidence_complete is False


def test_nonempty_exact_receipt_bound_evidence_completes_gate_without_authority() -> None:
    gate = evaluate_v24_parity_proof_gate(
        historical_evaluation=_historical_evaluation(4),
        forward_evaluation=_forward_evaluation(2),
        forward_deployment_evidence=_deployment_evidence(2),
    )
    assert gate.parity_evidence_complete is True
    assert gate.blockers == ()
    assert gate.forward_reference_signal_count == 2
    assert gate.forward_deployment_commit_sha == "b" * 40
    assert gate.promotion_authorized is False
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False


def test_proof_record_itself_cannot_smuggle_promotion_authority() -> None:
    try:
        V24ParityProofGate(
            historical_exact=True,
            historical_reference_signal_count=1,
            historical_parameter_manifest_locked=True,
            forward_exact=True,
            forward_reference_signal_count=1,
            forward_monitor_deployed=True,
            forward_deployment_commit_sha="b" * 40,
            blockers=(),
            parity_evidence_complete=True,
            promotion_authorized=True,
        )
    except ValueError as exc:
        assert str(exc) == "parity proof gate cannot authorize promotion"
    else:
        raise AssertionError("promotion authority must fail closed")
