from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.pine_bar_outcome_compare import BarOutcomeReport
from daily_alpha.pine_forward_locked_replay import LockedForwardV24Evaluation
from daily_alpha.pine_forward_reference import (
    PersistedReferenceSnapshot,
    ReceiptBoundForwardParityEvaluation,
)
from daily_alpha.pine_forward_replay_provenance import ForwardReplayProvenance
from daily_alpha.pine_historical_reference import HistoricalSourceArtifact
from daily_alpha.pine_historical_reference_locked import LockedHistoricalV24Evaluation
from daily_alpha.pine_paired_evidence_capture import PairedHistoricalEvidenceReadiness
from daily_alpha.pine_paired_parity_proof_gate import (
    PairedParityProofStatus,
    evaluate_paired_pine_parity_proof_gate,
)
from daily_alpha.pine_parameter_manifest import PineParameterManifest
from daily_alpha.pine_parity_compare import ParityReport, ReferenceSignal
from daily_alpha.pine_parity_proof_gate import V24ParityProofGate
from daily_alpha.pine_v24_evidence_readiness import (
    EvidenceArtifactState,
    HistoricalV24EvidenceReadiness,
)
from daily_alpha.pine_v24_parity import PINE_V24_SOURCE_BLOB_SHA, V24Parameters
from daily_alpha.pine_v25_evidence_readiness import HistoricalV25EvidenceReadiness
from daily_alpha.pine_v25_forward_locked_replay import LockedForwardV25Evaluation
from daily_alpha.pine_v25_historical_reference import HistoricalV25Evaluation
from daily_alpha.pine_v25_parity import PINE_V25_SOURCE_BLOB_SHA, V25Parameters
from daily_alpha.pine_v25_parity_proof_gate import V25ParityProofGate

START = datetime(2026, 8, 1, 20, tzinfo=UTC)
END = datetime(2026, 8, 21, 20, tzinfo=UTC)
MARKET_SHA = "2" * 64
MARKET_REVISION = "pit-market-revision"
DEPLOYMENT_COMMIT = "b" * 40
PROCESSOR_SHA = "processor-code-sha"


def _parity_report(*, exact: bool = True) -> ParityReport:
    return ParityReport(
        reference_count=1,
        python_count=1 if exact else 0,
        exact_match_count=1 if exact else 0,
        mismatch_count=0 if exact else 1,
        mismatches=(),
    )


def _bar_report(*, exact: bool = True) -> BarOutcomeReport:
    return BarOutcomeReport(
        reference_count=5,
        python_count=5 if exact else 4,
        exact_bar_count=5 if exact else 4,
        mismatch_count=0 if exact else 1,
        mismatches=(),
    )


def _historical_readiness() -> PairedHistoricalEvidenceReadiness:
    sh24 = HistoricalV24EvidenceReadiness(
        symbol="DINO",
        market_evidence_state=EvidenceArtifactState.PRESENT,
        tradingview_signal_state=EvidenceArtifactState.PRESENT,
        tradingview_bar_outcome_state=EvidenceArtifactState.PRESENT,
        parameter_manifest_state=EvidenceArtifactState.PRESENT,
        locked_reference_id="sh24-history",
        blockers=(),
        diagnostics=(),
    )
    sh25 = HistoricalV25EvidenceReadiness(
        symbol="DINO",
        market_evidence_state=EvidenceArtifactState.PRESENT,
        tradingview_signal_state=EvidenceArtifactState.PRESENT,
        tradingview_bar_outcome_state=EvidenceArtifactState.PRESENT,
        parameter_manifest_state=EvidenceArtifactState.PRESENT,
        locked_reference_id="sh25-history",
        blockers=(),
        diagnostics=(),
    )
    return PairedHistoricalEvidenceReadiness(
        symbol="DINO",
        sh24=sh24,
        sh25=sh25,
        sh24_instance_state=EvidenceArtifactState.PRESENT,
        sh25_instance_state=EvidenceArtifactState.PRESENT,
        shared_market_sha256="9" * 64,
        paired_capture_id="8" * 64,
        blockers=(),
        diagnostics=(),
    )


def _historical_evaluations(
    *, sh24_exact: bool = True, sh25_exact: bool = True
) -> tuple[LockedHistoricalV24Evaluation, HistoricalV25Evaluation]:
    return (
        LockedHistoricalV24Evaluation(
            reference_id="sh24-history",
            parameter_manifest_sha256="1" * 64,
            signal_report=_parity_report(exact=sh24_exact),
            bar_outcome_report=_bar_report(exact=sh24_exact),
        ),
        HistoricalV25Evaluation(
            reference_id="sh25-history",
            parameter_manifest_sha256="3" * 64,
            signal_report=_parity_report(exact=sh25_exact),
            bar_outcome_report=_bar_report(exact=sh25_exact),
        ),
    )


def _reference_signal(model_id: str) -> ReferenceSignal:
    return ReferenceSignal(
        symbol="DINO",
        bar_time=END,
        action="ENTRY_LONG",
        price=97.32,
        entry_type="NORMAL_BREAKOUT",
        runner_stage=None,
        quantity_units=None,
        source="TRADINGVIEW_PINE",
        source_id=f"{model_id}-EVENT-1",
    )


def _forward_provenance(
    *, model_id: str, strategy_version: str, source_blob_sha: str, parameter_sha: str
) -> ForwardReplayProvenance:
    return ForwardReplayProvenance(
        model_id=model_id,
        strategy_version=strategy_version,
        strategy_source_blob_sha=source_blob_sha,
        parameter_manifest_sha256=parameter_sha,
        market_evidence_sha256=MARKET_SHA,
        market_source_revision=MARKET_REVISION,
        python_engine_revision=f"{model_id}-engine-revision",
        replay_start=START,
        replay_end=END,
        replay_bar_count=15,
        deployment_commit_sha=DEPLOYMENT_COMMIT,
        processor_code_sha256=PROCESSOR_SHA,
    )


def _receipt(
    *, model_id: str, strategy_version: str, provenance: ForwardReplayProvenance
) -> ReceiptBoundForwardParityEvaluation:
    signal = _reference_signal(model_id)
    return ReceiptBoundForwardParityEvaluation(
        model_id=model_id,
        strategy_version=strategy_version,
        deployment_commit_sha=DEPLOYMENT_COMMIT,
        processor_code_sha256=PROCESSOR_SHA,
        reference_snapshot=PersistedReferenceSnapshot(
            model_id=model_id,
            strategy_version=strategy_version,
            event_count_visible=1,
            event_limit=100,
            scan_items_evaluated=1,
            signals=(signal,),
        ),
        report=_parity_report(),
        replay_provenance=provenance,
    )


def _forward_evaluations() -> tuple[LockedForwardV24Evaluation, LockedForwardV25Evaluation]:
    v24_provenance = _forward_provenance(
        model_id="PAPER_SHADOW_V24",
        strategy_version="2.4",
        source_blob_sha=PINE_V24_SOURCE_BLOB_SHA,
        parameter_sha="1" * 64,
    )
    v25_provenance = _forward_provenance(
        model_id="PAPER_SHADOW_V25",
        strategy_version="2.5",
        source_blob_sha=PINE_V25_SOURCE_BLOB_SHA,
        parameter_sha="3" * 64,
    )
    market_artifact = HistoricalSourceArtifact(
        source="POINT_IN_TIME_TEST_MARKET",
        revision=MARKET_REVISION,
        sha256=MARKET_SHA,
        row_count=15,
    )
    sh24 = LockedForwardV24Evaluation(
        evaluation=_receipt(
            model_id="PAPER_SHADOW_V24",
            strategy_version="2.4",
            provenance=v24_provenance,
        ),
        market_artifact=market_artifact,
        parameter_manifest=PineParameterManifest(
            model_id="PAPER_SHADOW_V24",
            strategy_version="2.4",
            source_blob_sha=PINE_V24_SOURCE_BLOB_SHA,
            process_orders_on_close=True,
            parameters=V24Parameters(),
            sha256="1" * 64,
        ),
        market_start_iso=START.isoformat(),
        market_end_iso=END.isoformat(),
        replay_python_signal_count=1,
    )
    sh25 = LockedForwardV25Evaluation(
        evaluation=_receipt(
            model_id="PAPER_SHADOW_V25",
            strategy_version="2.5",
            provenance=v25_provenance,
        ),
        market_artifact=market_artifact,
        parameter_manifest=PineParameterManifest(
            model_id="PAPER_SHADOW_V25",
            strategy_version="2.5",
            source_blob_sha=PINE_V25_SOURCE_BLOB_SHA,
            process_orders_on_close=True,
            parameters=V25Parameters(),
            sha256="3" * 64,
        ),
        market_start_iso=START.isoformat(),
        market_end_iso=END.isoformat(),
        replay_python_signal_count=1,
    )
    return sh24, sh25


def _gates(
    sh24_forward: LockedForwardV24Evaluation,
    sh25_forward: LockedForwardV25Evaluation,
    *,
    sh24_historical_exact: bool = True,
) -> tuple[V24ParityProofGate, V25ParityProofGate]:
    sh24_blockers = () if sh24_historical_exact else ("HISTORICAL_PARITY_MISMATCH",)
    sh24 = V24ParityProofGate(
        historical_exact=sh24_historical_exact,
        historical_reference_signal_count=1,
        historical_parameter_manifest_locked=True,
        forward_exact=True,
        forward_reference_signal_count=1,
        forward_monitor_deployed=True,
        forward_deployment_commit_sha=DEPLOYMENT_COMMIT,
        forward_replay_inputs_locked=True,
        forward_replay_evidence_id=sh24_forward.replay_provenance.evidence_id,
        blockers=sh24_blockers,
        parity_evidence_complete=not sh24_blockers,
    )
    sh25 = V25ParityProofGate(
        historical_exact=True,
        historical_reference_signal_count=1,
        historical_parameter_manifest_locked=True,
        forward_exact=True,
        forward_reference_signal_count=1,
        forward_monitor_deployed=True,
        forward_deployment_commit_sha=DEPLOYMENT_COMMIT,
        forward_replay_inputs_locked=True,
        forward_replay_evidence_id=sh25_forward.replay_provenance.evidence_id,
        blockers=(),
        parity_evidence_complete=True,
    )
    return sh24, sh25


def test_missing_paired_capture_is_not_misreported_as_failed_parity() -> None:
    sh24_forward, sh25_forward = _forward_evaluations()
    sh24_gate, sh25_gate = _gates(sh24_forward, sh25_forward)
    sh24_history, sh25_history = _historical_evaluations()

    proof = evaluate_paired_pine_parity_proof_gate(
        historical_readiness=None,
        sh24_historical_evaluation=sh24_history,
        sh25_historical_evaluation=sh25_history,
        sh24_forward_evaluation=sh24_forward,
        sh25_forward_evaluation=sh25_forward,
        sh24_gate=sh24_gate,
        sh25_gate=sh25_gate,
    )

    assert proof.status is PairedParityProofStatus.MISSING_EXTERNAL_EVIDENCE
    assert "PAIRED_HISTORICAL_EVIDENCE_MISSING" in proof.blockers
    assert proof.proof_id is None
    assert proof.trading_authorized is False
    assert proof.live_trading_enabled is False


def test_observed_comparison_mismatch_is_classified_as_failed_parity_without_retuning() -> None:
    sh24_forward, sh25_forward = _forward_evaluations()
    sh24_gate, sh25_gate = _gates(
        sh24_forward,
        sh25_forward,
        sh24_historical_exact=False,
    )
    sh24_history, sh25_history = _historical_evaluations(sh24_exact=False)

    proof = evaluate_paired_pine_parity_proof_gate(
        historical_readiness=_historical_readiness(),
        sh24_historical_evaluation=sh24_history,
        sh25_historical_evaluation=sh25_history,
        sh24_forward_evaluation=sh24_forward,
        sh25_forward_evaluation=sh25_forward,
        sh24_gate=sh24_gate,
        sh25_gate=sh25_gate,
    )

    assert proof.status is PairedParityProofStatus.FAILED_PARITY
    assert "SH24:HISTORICAL_PARITY_MISMATCH" in proof.blockers
    assert proof.proof_id is None


def test_exact_control_and_challenger_are_bound_to_one_historical_and_forward_cohort() -> None:
    sh24_forward, sh25_forward = _forward_evaluations()
    sh24_gate, sh25_gate = _gates(sh24_forward, sh25_forward)
    sh24_history, sh25_history = _historical_evaluations()

    proof = evaluate_paired_pine_parity_proof_gate(
        historical_readiness=_historical_readiness(),
        sh24_historical_evaluation=sh24_history,
        sh25_historical_evaluation=sh25_history,
        sh24_forward_evaluation=sh24_forward,
        sh25_forward_evaluation=sh25_forward,
        sh24_gate=sh24_gate,
        sh25_gate=sh25_gate,
    )

    assert proof.status is PairedParityProofStatus.PASSED
    assert proof.blockers == ()
    assert proof.paired_capture_id == "8" * 64
    assert proof.shared_forward_market_sha256 == MARKET_SHA
    assert proof.shared_forward_market_revision == MARKET_REVISION
    assert proof.shared_forward_deployment_commit_sha == DEPLOYMENT_COMMIT
    assert proof.sh24_forward_replay_evidence_id != proof.sh25_forward_replay_evidence_id
    assert proof.proof_id is not None
    assert proof.promotion_authorized is False
    assert proof.trading_authorized is False
    assert proof.live_trading_enabled is False


def test_cross_wired_forward_market_evidence_blocks_proof_without_calling_it_parity_failure() -> None:
    sh24_forward, sh25_forward = _forward_evaluations()
    sh25_forward = LockedForwardV25Evaluation(
        evaluation=ReceiptBoundForwardParityEvaluation(
            model_id=sh25_forward.model_id,
            strategy_version=sh25_forward.strategy_version,
            deployment_commit_sha=sh25_forward.deployment_commit_sha,
            processor_code_sha256=sh25_forward.processor_code_sha256,
            reference_snapshot=sh25_forward.reference_snapshot,
            report=sh25_forward.report,
            replay_provenance=ForwardReplayProvenance(
                model_id="PAPER_SHADOW_V25",
                strategy_version="2.5",
                strategy_source_blob_sha=PINE_V25_SOURCE_BLOB_SHA,
                parameter_manifest_sha256="3" * 64,
                market_evidence_sha256="4" * 64,
                market_source_revision="different-market-revision",
                python_engine_revision="PAPER_SHADOW_V25-engine-revision",
                replay_start=START,
                replay_end=END,
                replay_bar_count=15,
                deployment_commit_sha=DEPLOYMENT_COMMIT,
                processor_code_sha256=PROCESSOR_SHA,
            ),
        ),
        market_artifact=HistoricalSourceArtifact(
            source="POINT_IN_TIME_TEST_MARKET",
            revision="different-market-revision",
            sha256="4" * 64,
            row_count=15,
        ),
        parameter_manifest=sh25_forward.parameter_manifest,
        market_start_iso=START.isoformat(),
        market_end_iso=END.isoformat(),
        replay_python_signal_count=1,
    )
    sh24_gate, sh25_gate = _gates(sh24_forward, sh25_forward)
    sh24_history, sh25_history = _historical_evaluations()

    proof = evaluate_paired_pine_parity_proof_gate(
        historical_readiness=_historical_readiness(),
        sh24_historical_evaluation=sh24_history,
        sh25_historical_evaluation=sh25_history,
        sh24_forward_evaluation=sh24_forward,
        sh25_forward_evaluation=sh25_forward,
        sh24_gate=sh24_gate,
        sh25_gate=sh25_gate,
    )

    assert proof.status is PairedParityProofStatus.MISSING_EXTERNAL_EVIDENCE
    assert "CONTROL_CHALLENGER_FORWARD_MARKET_EVIDENCE_NOT_IDENTICAL" in proof.blockers
    assert proof.proof_id is None
