from datetime import UTC, datetime

from daily_alpha.pine_bar_outcome_compare import BarOutcomeReport
from daily_alpha.pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardParityDeploymentEvidence,
    ForwardPersistedEventEvidence,
)
from daily_alpha.pine_forward_event_classification import EXPLICIT_STAGING_E2E_SIGNAL_IDS
from daily_alpha.pine_forward_reference import (
    PersistedReferenceSnapshot,
    ReceiptBoundForwardParityEvaluation,
)
from daily_alpha.pine_forward_replay_provenance import ForwardReplayProvenance
from daily_alpha.pine_historical_reference import HistoricalSourceArtifact
from daily_alpha.pine_parameter_manifest import PineParameterManifest
from daily_alpha.pine_parity_compare import ParityReport, ReferenceSignal
from daily_alpha.pine_v25_forward_locked_replay import LockedForwardV25Evaluation
from daily_alpha.pine_v25_historical_reference import HistoricalV25Evaluation
from daily_alpha.pine_v25_parity import V25Parameters
from daily_alpha.pine_v25_parity_proof_gate import (
    V25ParityProofGate,
    evaluate_v25_parity_proof_gate,
)

NOW = datetime(2026, 8, 21, 20, tzinfo=UTC)
START = datetime(2026, 8, 1, 20, tzinfo=UTC)


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


def _persisted_event(signal_id: str, *, natural: bool) -> ForwardPersistedEventEvidence:
    fields = {
        "signal_id": signal_id,
        "symbol": "DINO" if natural else "DAE2E",
        "action": "ENTRY_LONG" if natural else "ADD",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.5",
        "model_id": "PAPER_SHADOW_V25",
        "timeframe": "1D" if natural else "D",
        "price": 97.32 if natural else 100.0,
        "bar_time": NOW.isoformat(),
        "entry_type": "NORMAL_BREAKOUT" if natural else None,
        "runner_stage": None if natural else "ADD_1_ATR",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V25",
        signal_id=signal_id,
        fields=tuple(sorted(fields.items())),
    )


def _book(account_id: str, *, include_natural: bool = False, include_e2e: bool = False):
    events: tuple[ForwardPersistedEventEvidence, ...] = ()
    if account_id == "PAPER_SHADOW_V25":
        collected: list[ForwardPersistedEventEvidence] = []
        if include_natural:
            collected.append(_persisted_event("DINO-1787342400000-ENTRY_LONG", natural=True))
        if include_e2e:
            collected.extend(
                _persisted_event(signal_id, natural=False)
                for signal_id in sorted(EXPLICIT_STAGING_E2E_SIGNAL_IDS)
            )
        events = tuple(collected)
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


def _deployment_evidence(*, include_natural: bool = True, include_e2e: bool = True):
    return ForwardParityDeploymentEvidence(
        repository="shannonburgess/daily-alpha-engine1",
        commit_sha="c" * 40,
        workflow_run_id="32650476819",
        workflow_run_attempt="1",
        processor_version="$LATEST",
        processor_code_sha256="code-hash",
        sh24=_book("PAPER_SHADOW_V24"),
        sh25=_book(
            "PAPER_SHADOW_V25",
            include_natural=include_natural,
            include_e2e=include_e2e,
        ),
    )


def _replay_provenance(commit_sha: str = "c" * 40) -> ForwardReplayProvenance:
    return ForwardReplayProvenance(
        model_id="PAPER_SHADOW_V25",
        strategy_version="2.5",
        strategy_source_blob_sha="2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5",
        parameter_manifest_sha256="3" * 64,
        market_evidence_sha256="4" * 64,
        market_source_revision="point-in-time-market-revision",
        python_engine_revision="pine_v25_parity.py:test-revision",
        replay_start=START,
        replay_end=NOW,
        replay_bar_count=15,
        deployment_commit_sha=commit_sha,
        processor_code_sha256="code-hash",
    )


def _forward_evaluation(
    count: int,
    *,
    exact: bool = True,
    commit_sha: str = "c" * 40,
    carry_provenance: bool = True,
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
            source_id=f"SH25-NATURAL-{index}",
        )
        for index in range(count)
    )
    return ReceiptBoundForwardParityEvaluation(
        model_id="PAPER_SHADOW_V25",
        strategy_version="2.5",
        deployment_commit_sha=commit_sha,
        processor_code_sha256="code-hash",
        reference_snapshot=PersistedReferenceSnapshot(
            model_id="PAPER_SHADOW_V25",
            strategy_version="2.5",
            event_count_visible=count,
            event_limit=100,
            scan_items_evaluated=count,
            signals=signals,
        ),
        report=_report(count, exact=exact),
        replay_provenance=_replay_provenance(commit_sha) if carry_provenance else None,
    )


def _locked_forward_evaluation(
    count: int,
    *,
    exact: bool = True,
    commit_sha: str = "c" * 40,
) -> LockedForwardV25Evaluation:
    evaluation = _forward_evaluation(count, exact=exact, commit_sha=commit_sha)
    return LockedForwardV25Evaluation(
        evaluation=evaluation,
        market_artifact=HistoricalSourceArtifact(
            source="POINT_IN_TIME_TEST_MARKET",
            revision="point-in-time-market-revision",
            sha256="4" * 64,
            row_count=15,
        ),
        parameter_manifest=PineParameterManifest(
            model_id="PAPER_SHADOW_V25",
            strategy_version="2.5",
            source_blob_sha="2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5",
            process_orders_on_close=True,
            parameters=V25Parameters(),
            sha256="3" * 64,
        ),
        market_start_iso=START.isoformat(),
        market_end_iso=NOW.isoformat(),
        replay_python_signal_count=evaluation.report.python_count,
    )


def test_v25_missing_evidence_fails_closed() -> None:
    gate = evaluate_v25_parity_proof_gate(
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


def test_v25_exact_empty_comparisons_are_not_proof_even_with_retained_e2e_events() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(0),
        forward_evaluation=_locked_forward_evaluation(0),
        forward_deployment_evidence=_deployment_evidence(
            include_natural=False,
            include_e2e=True,
        ),
    )
    assert gate.parity_evidence_complete is False
    assert gate.blockers == (
        "HISTORICAL_GENUINE_SIGNAL_EVIDENCE_EMPTY",
        "FORWARD_GENUINE_SIGNAL_EVIDENCE_EMPTY",
    )


def test_v25_monitor_deployment_receipt_is_required_for_forward_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(3),
        forward_evaluation=_locked_forward_evaluation(1),
        forward_deployment_evidence=None,
    )
    assert gate.parity_evidence_complete is False
    assert "FORWARD_PARITY_MONITOR_DEPLOYMENT_EVIDENCE_MISSING" in gate.blockers
    assert "FORWARD_PARITY_EVALUATION_NOT_DEPLOYMENT_BOUND" in gate.blockers


def test_v25_receipt_match_without_verified_replay_inputs_cannot_complete_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(3),
        forward_evaluation=_forward_evaluation(1, carry_provenance=False),
        forward_deployment_evidence=_deployment_evidence(),
    )
    assert gate.parity_evidence_complete is False
    assert gate.forward_replay_inputs_locked is False
    assert gate.forward_replay_evidence_id is None
    assert gate.blockers == ("FORWARD_REPLAY_INPUT_EVIDENCE_NOT_LOCKED",)


def test_v25_caller_constructed_provenance_alone_cannot_complete_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(3),
        forward_evaluation=_forward_evaluation(1, carry_provenance=True),
        forward_deployment_evidence=_deployment_evidence(),
    )
    assert gate.parity_evidence_complete is False
    assert gate.forward_replay_inputs_locked is False
    assert gate.blockers == ("FORWARD_REPLAY_INPUT_EVIDENCE_NOT_LOCKED",)


def test_v25_receipt_raw_count_does_not_mistake_e2e_events_for_genuine_signals() -> None:
    deployment = _deployment_evidence(include_natural=True, include_e2e=True)
    assert deployment.sh25.event_count_visible == 4

    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(4),
        forward_evaluation=_locked_forward_evaluation(1),
        forward_deployment_evidence=deployment,
    )
    assert gate.parity_evidence_complete is True
    assert gate.forward_reference_signal_count == 1
    assert gate.forward_replay_inputs_locked is True
    assert gate.blockers == ()


def test_v25_receipt_identity_or_genuine_count_mismatch_blocks_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(4),
        forward_evaluation=_locked_forward_evaluation(2, commit_sha="d" * 40),
        forward_deployment_evidence=_deployment_evidence(),
    )
    assert "FORWARD_PARITY_DEPLOYMENT_COMMIT_MISMATCH" in gate.blockers
    assert "FORWARD_PARITY_RECEIPT_EVENT_COUNT_MISMATCH" in gate.blockers
    assert gate.parity_evidence_complete is False


def test_v25_mismatch_blocks_evidence_completion_without_retuning() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(4, exact=False),
        forward_evaluation=_locked_forward_evaluation(1, exact=False),
        forward_deployment_evidence=_deployment_evidence(),
    )
    assert gate.parity_evidence_complete is False
    assert gate.blockers == ("HISTORICAL_PARITY_MISMATCH", "FORWARD_PARITY_MISMATCH")


def test_v25_exact_nonempty_verified_replay_completes_only_evidence_gate() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(4),
        forward_evaluation=_locked_forward_evaluation(1),
        forward_deployment_evidence=_deployment_evidence(),
    )
    assert gate.parity_evidence_complete is True
    assert gate.blockers == ()
    assert gate.historical_reference_signal_count == 4
    assert gate.forward_reference_signal_count == 1
    assert gate.forward_deployment_commit_sha == "c" * 40
    assert gate.forward_replay_inputs_locked is True
    assert gate.forward_replay_evidence_id is not None
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
            forward_deployment_commit_sha="c" * 40,
            forward_replay_inputs_locked=True,
            forward_replay_evidence_id="d" * 64,
            blockers=(),
            parity_evidence_complete=True,
            promotion_authorized=True,
        )
    except ValueError as exc:
        assert str(exc) == "parity proof gate cannot authorize promotion"
    else:
        raise AssertionError("promotion authority must fail closed")
