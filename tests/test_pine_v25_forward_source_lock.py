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
from daily_alpha.pine_forward_replay_provenance import ForwardReplayProvenance
from daily_alpha.pine_parity_compare import ParityReport, ReferenceSignal
from daily_alpha.pine_v25_historical_reference import HistoricalV25Evaluation
from daily_alpha.pine_v25_parity_proof_gate import evaluate_v25_parity_proof_gate

NOW = datetime(2026, 8, 21, 20, tzinfo=UTC)


def _report() -> ParityReport:
    return ParityReport(
        reference_count=1,
        python_count=1,
        exact_match_count=1,
        mismatch_count=0,
        mismatches=(),
    )


def _history() -> HistoricalV25Evaluation:
    return HistoricalV25Evaluation(
        reference_id="locked-v25-history",
        parameter_manifest_sha256="a" * 64,
        signal_report=_report(),
        bar_outcome_report=BarOutcomeReport(
            reference_count=1,
            python_count=1,
            exact_bar_count=1,
            mismatch_count=0,
            mismatches=(),
        ),
    )


def _empty_book(account_id: str) -> ForwardParityBookEvidence:
    return ForwardParityBookEvidence(
        account_id=account_id,
        event_count_visible=0,
        event_count_scanned=0,
        event_history_omitted=0,
        event_limit=100,
        scan_pages=1,
        scan_items_evaluated=0,
        open_count=0,
        armed_count_visible=0,
        events=(),
    )


def _deployment() -> ForwardParityDeploymentEvidence:
    signal_id = "DINO-1787342400000-ENTRY_LONG"
    event = ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V25",
        signal_id=signal_id,
        fields=tuple(
            sorted(
                {
                    "signal_id": signal_id,
                    "symbol": "DINO",
                    "action": "ENTRY_LONG",
                    "source": "TRADINGVIEW_PINE",
                    "strategy": "DA_TURTLE_ADAPTIVE_TREND",
                    "strategy_version": "2.5",
                    "model_id": "PAPER_SHADOW_V25",
                    "timeframe": "1D",
                    "price": 97.32,
                    "bar_time": NOW.isoformat(),
                    "entry_type": "NORMAL_BREAKOUT",
                    "trading_authorized": False,
                    "live_trading_enabled": False,
                }.items()
            )
        ),
    )
    sh25 = ForwardParityBookEvidence(
        account_id="PAPER_SHADOW_V25",
        event_count_visible=1,
        event_count_scanned=1,
        event_history_omitted=0,
        event_limit=100,
        scan_pages=1,
        scan_items_evaluated=1,
        open_count=0,
        armed_count_visible=0,
        events=(event,),
    )
    return ForwardParityDeploymentEvidence(
        repository="shannonburgess/daily-alpha-engine1",
        commit_sha="c" * 40,
        workflow_run_id="run",
        workflow_run_attempt="1",
        processor_version="$LATEST",
        processor_code_sha256="code-hash",
        sh24=_empty_book("PAPER_SHADOW_V24"),
        sh25=sh25,
    )


def _forward(source_blob_sha: str) -> ReceiptBoundForwardParityEvaluation:
    signal = ReferenceSignal(
        symbol="DINO",
        bar_time=NOW,
        action="ENTRY_LONG",
        price=97.32,
        entry_type="NORMAL_BREAKOUT",
        runner_stage=None,
        quantity_units=None,
        source="TRADINGVIEW_PINE",
        source_id="DINO-1787342400000-ENTRY_LONG",
    )
    provenance = ForwardReplayProvenance(
        model_id="PAPER_SHADOW_V25",
        strategy_version="2.5",
        strategy_source_blob_sha=source_blob_sha,
        parameter_manifest_sha256="3" * 64,
        market_evidence_sha256="4" * 64,
        market_source_revision="market-revision",
        python_engine_revision="engine-revision",
        replay_start=datetime(2026, 7, 1, 20, tzinfo=UTC),
        replay_end=NOW,
        replay_bar_count=40,
        deployment_commit_sha="c" * 40,
        processor_code_sha256="code-hash",
    )
    return ReceiptBoundForwardParityEvaluation(
        model_id="PAPER_SHADOW_V25",
        strategy_version="2.5",
        deployment_commit_sha="c" * 40,
        processor_code_sha256="code-hash",
        reference_snapshot=PersistedReferenceSnapshot(
            model_id="PAPER_SHADOW_V25",
            strategy_version="2.5",
            event_count_visible=1,
            event_limit=100,
            scan_items_evaluated=1,
            signals=(signal,),
        ),
        report=_report(),
        replay_provenance=provenance,
    )


def test_wrong_frozen_source_cannot_complete_sh25_forward_proof() -> None:
    gate = evaluate_v25_parity_proof_gate(
        historical_evaluation=_history(),
        forward_evaluation=_forward("e" * 40),
        forward_deployment_evidence=_deployment(),
    )

    assert gate.parity_evidence_complete is False
    assert gate.forward_replay_inputs_locked is True
    assert gate.blockers == ("FORWARD_REPLAY_SOURCE_MISMATCH",)
