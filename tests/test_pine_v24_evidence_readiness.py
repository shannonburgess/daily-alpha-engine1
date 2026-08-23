import dataclasses
import json
from datetime import UTC, datetime, timedelta

from daily_alpha.pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardParityDeploymentEvidence,
    ForwardPersistedEventEvidence,
)
from daily_alpha.pine_v24_evidence_readiness import (
    EvidenceArtifactState,
    assess_forward_v24_evidence_readiness,
    assess_historical_v24_evidence_readiness,
)
from daily_alpha.pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_STRATEGY_VERSION,
    V24Parameters,
)

BASE = datetime(2026, 7, 20, 20, tzinfo=UTC)


def _manifest() -> str:
    parameters = V24Parameters()
    values = {}
    for field in dataclasses.fields(parameters):
        value = getattr(parameters, field.name)
        values[field.name] = value.isoformat() if isinstance(value, datetime) else value
    return json.dumps(
        {
            "model_id": PINE_V24_MODEL_ID,
            "strategy_version": PINE_V24_STRATEGY_VERSION,
            "source_blob_sha": PINE_V24_SOURCE_BLOB_SHA,
            "process_orders_on_close": True,
            "parameters": values,
        },
        sort_keys=True,
    )


def _market_csv(days: int = 35) -> str:
    header = (
        "time,symbol,open,high,low,close,volume,earnings_state,earnings_actual,"
        "earnings_known_at,source_id"
    )
    rows = [header]
    for index in range(days):
        bar_time = BASE + timedelta(days=index)
        rows.append(
            f"{bar_time.isoformat()},DINO,100,101,99,100,2000000,NONE,,,DINO-{index}"
        )
    return "\n".join(rows) + "\n"


def _signal_csv() -> str:
    return (
        "bar_time,symbol,action,price,entry_type,runner_stage,quantity_units,source_id\n"
    )


def _bar_outcome_csv(days: int = 35) -> str:
    rows = [
        "bar_time,symbol,outcome_kind,signal_actions,rejection_reasons,entry_type,source_id"
    ]
    for index in range(days):
        bar_time = BASE + timedelta(days=index)
        rows.append(f"{bar_time.isoformat()},DINO,NO_TRADE,,,NONE,TV-OUTCOME-{index}")
    return "\n".join(rows) + "\n"


def _event(bar_time: datetime) -> ForwardPersistedEventEvidence:
    fields = {
        "signal_id": "DINO-1787342400000-ENTRY_LONG",
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "model_id": "PAPER_SHADOW_V24",
        "timeframe": "1D",
        "price": 97.32,
        "bar_time": bar_time.isoformat(),
        "entry_type": "NORMAL_BREAKOUT",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V24",
        signal_id="DINO-1787342400000-ENTRY_LONG",
        fields=tuple(sorted(fields.items())),
    )


def _book(account_id: str, events=()) -> ForwardParityBookEvidence:
    return ForwardParityBookEvidence(
        account_id=account_id,
        event_count_visible=len(events),
        event_count_scanned=len(events),
        event_history_omitted=0,
        event_limit=100,
        scan_pages=1,
        scan_items_evaluated=max(1, len(events)),
        open_count=0,
        armed_count_visible=0,
        events=tuple(events),
    )


def _deployment(event_time: datetime) -> ForwardParityDeploymentEvidence:
    return ForwardParityDeploymentEvidence(
        repository="shannonburgess/daily-alpha-engine1",
        commit_sha="9fd6affcbdd7914ff611b029103c95794c7ed3bb",
        workflow_run_id="32651982887",
        workflow_run_attempt="1",
        processor_version="$LATEST",
        processor_code_sha256="processor-code-hash",
        sh24=_book("PAPER_SHADOW_V24", (_event(event_time),)),
        sh25=_book("PAPER_SHADOW_V25"),
    )


def test_forward_readiness_reports_exact_missing_artifact_classes() -> None:
    event_time = BASE + timedelta(days=34)
    readiness = assess_forward_v24_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
    )

    assert readiness.ready_for_locked_replay is False
    assert readiness.reference_signal_ids == ("DINO-1787342400000-ENTRY_LONG",)
    assert readiness.market_evidence_state is EvidenceArtifactState.MISSING
    assert readiness.parameter_manifest_state is EvidenceArtifactState.MISSING
    assert "POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_MISSING" in readiness.blockers
    assert "EXACT_PINE_PARAMETER_MANIFEST_MISSING" in readiness.blockers
    assert "MARKET_SOURCE_IDENTITY_MISSING" in readiness.blockers
    assert "MARKET_SOURCE_REVISION_MISSING" in readiness.blockers
    assert "PYTHON_ENGINE_REVISION_MISSING" in readiness.blockers
    assert readiness.trading_authorized is False
    assert readiness.live_trading_enabled is False


def test_forward_readiness_accepts_exact_replay_inputs_without_claiming_parity() -> None:
    event_time = BASE + timedelta(days=34)
    readiness = assess_forward_v24_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
        market_csv=_market_csv(),
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-2026-08-21-v1",
        python_engine_revision="pine_v24_parity.py@d523b589",
    )

    assert readiness.ready_for_locked_replay is True
    assert readiness.blockers == ()
    assert readiness.market_evidence_state is EvidenceArtifactState.PRESENT
    assert readiness.parameter_manifest_state is EvidenceArtifactState.PRESENT
    assert readiness.market_evidence_sha256 is not None
    assert readiness.parameter_manifest_sha256 is not None


def test_forward_readiness_requires_genuine_event_bar_inside_market_evidence() -> None:
    event_time = BASE + timedelta(days=60)
    readiness = assess_forward_v24_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
        market_csv=_market_csv(),
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-2026-08-21-v1",
        python_engine_revision="pine_v24_parity.py@d523b589",
    )

    assert readiness.ready_for_locked_replay is False
    assert "REFERENCE_EVENT_BAR_MISSING_FROM_MARKET_EVIDENCE" in readiness.blockers
    assert readiness.market_evidence_state is EvidenceArtifactState.PRESENT


def test_forward_readiness_rejects_noncanonical_order_timing_manifest() -> None:
    payload = json.loads(_manifest())
    payload["process_orders_on_close"] = False
    event_time = BASE + timedelta(days=34)
    readiness = assess_forward_v24_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
        market_csv=_market_csv(),
        parameter_manifest_json=json.dumps(payload),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-2026-08-21-v1",
        python_engine_revision="pine_v24_parity.py@d523b589",
    )

    assert readiness.parameter_manifest_state is EvidenceArtifactState.INVALID
    assert "EXACT_PINE_PARAMETER_MANIFEST_INVALID" in readiness.blockers
    assert any("PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE" in item for item in readiness.diagnostics)


def test_historical_readiness_reports_every_missing_proof_artifact() -> None:
    readiness = assess_historical_v24_evidence_readiness(symbol="DINO")

    assert readiness.ready_for_locked_reference is False
    assert "POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_MISSING" in readiness.blockers
    assert "TRADINGVIEW_SIGNAL_REFERENCE_MISSING" in readiness.blockers
    assert "TRADINGVIEW_BAR_OUTCOME_REFERENCE_MISSING" in readiness.blockers
    assert "EXACT_PINE_PARAMETER_MANIFEST_MISSING" in readiness.blockers
    assert readiness.locked_reference_id is None


def test_historical_readiness_builds_locked_reference_only_from_complete_bundle() -> None:
    readiness = assess_historical_v24_evidence_readiness(
        symbol="DINO",
        market_csv=_market_csv(),
        tradingview_signal_csv=_signal_csv(),
        tradingview_bar_outcome_csv=_bar_outcome_csv(),
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-HISTORICAL-V1",
        tradingview_source="TRADINGVIEW_EXPORT",
        tradingview_signal_revision="TV-SIGNALS-V1",
        tradingview_bar_outcome_revision="TV-BAR-OUTCOMES-V1",
    )

    assert readiness.ready_for_locked_reference is True
    assert readiness.blockers == ()
    assert readiness.locked_reference_id is not None
    assert readiness.market_evidence_state is EvidenceArtifactState.PRESENT
    assert readiness.tradingview_signal_state is EvidenceArtifactState.PRESENT
    assert readiness.tradingview_bar_outcome_state is EvidenceArtifactState.PRESENT
    assert readiness.parameter_manifest_state is EvidenceArtifactState.PRESENT


def test_historical_readiness_rejects_incomplete_bar_outcome_coverage() -> None:
    incomplete = "\n".join(_bar_outcome_csv().splitlines()[:-1]) + "\n"
    readiness = assess_historical_v24_evidence_readiness(
        symbol="DINO",
        market_csv=_market_csv(),
        tradingview_signal_csv=_signal_csv(),
        tradingview_bar_outcome_csv=incomplete,
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-HISTORICAL-V1",
        tradingview_source="TRADINGVIEW_EXPORT",
        tradingview_signal_revision="TV-SIGNALS-V1",
        tradingview_bar_outcome_revision="TV-BAR-OUTCOMES-V1",
    )

    assert readiness.ready_for_locked_reference is False
    assert "HISTORICAL_EVIDENCE_BUNDLE_INVALID" in readiness.blockers
    assert readiness.tradingview_bar_outcome_state is EvidenceArtifactState.INVALID
