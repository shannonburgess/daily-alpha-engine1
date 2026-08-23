import dataclasses
import json
from datetime import UTC, datetime, timedelta

from daily_alpha.pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardParityDeploymentEvidence,
    ForwardPersistedEventEvidence,
)
from daily_alpha.pine_v24_evidence_readiness import EvidenceArtifactState
from daily_alpha.pine_v25_evidence_readiness import (
    assess_forward_v25_evidence_readiness,
    assess_historical_v25_evidence_readiness,
)
from daily_alpha.pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_BLOB_SHA,
    PINE_V25_STRATEGY_VERSION,
    V25Parameters,
)

BASE = datetime(2026, 7, 20, 20, tzinfo=UTC)


def _manifest() -> str:
    parameters = V25Parameters()
    values = {}
    for field in dataclasses.fields(parameters):
        value = getattr(parameters, field.name)
        values[field.name] = value.isoformat() if isinstance(value, datetime) else value
    return json.dumps(
        {
            "model_id": PINE_V25_MODEL_ID,
            "strategy_version": PINE_V25_STRATEGY_VERSION,
            "source_blob_sha": PINE_V25_SOURCE_BLOB_SHA,
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
        rows.append(f"{bar_time.isoformat()},DINO,NO_TRADE,,,NONE,V25-OUTCOME-{index}")
    return "\n".join(rows) + "\n"


def _event(bar_time: datetime) -> ForwardPersistedEventEvidence:
    fields = {
        "signal_id": "DINO-1787342400000-ENTRY_LONG",
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.5",
        "model_id": "PAPER_SHADOW_V25",
        "timeframe": "1D",
        "price": 97.32,
        "bar_time": bar_time.isoformat(),
        "entry_type": "NORMAL_BREAKOUT",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V25",
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
        sh24=_book("PAPER_SHADOW_V24"),
        sh25=_book("PAPER_SHADOW_V25", (_event(event_time),)),
    )


def test_forward_sh25_readiness_reports_missing_exact_replay_inputs() -> None:
    event_time = BASE + timedelta(days=34)
    readiness = assess_forward_v25_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
    )

    assert readiness.ready_for_locked_replay is False
    assert readiness.reference_signal_ids == ("DINO-1787342400000-ENTRY_LONG",)
    assert "POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_MISSING" in readiness.blockers
    assert "EXACT_PINE_PARAMETER_MANIFEST_MISSING" in readiness.blockers
    assert readiness.trading_authorized is False
    assert readiness.live_trading_enabled is False


def test_forward_sh25_readiness_requires_complete_v25_manifest_and_event_bar() -> None:
    event_time = BASE + timedelta(days=34)
    readiness = assess_forward_v25_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
        market_csv=_market_csv(),
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-2026-08-21-v1",
        python_engine_revision="pine_v25_parity.py@0e412330",
    )

    assert readiness.ready_for_locked_replay is True
    assert readiness.blockers == ()
    assert readiness.market_evidence_state is EvidenceArtifactState.PRESENT
    assert readiness.parameter_manifest_state is EvidenceArtifactState.PRESENT


def test_forward_sh25_readiness_rejects_missing_shadow_forward_start() -> None:
    payload = json.loads(_manifest())
    del payload["parameters"]["shadow_forward_start"]
    event_time = BASE + timedelta(days=34)
    readiness = assess_forward_v25_evidence_readiness(
        deployment=_deployment(event_time),
        symbol="DINO",
        market_csv=_market_csv(),
        parameter_manifest_json=json.dumps(payload),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-2026-08-21-v1",
        python_engine_revision="pine_v25_parity.py@0e412330",
    )

    assert readiness.parameter_manifest_state is EvidenceArtifactState.INVALID
    assert "EXACT_PINE_PARAMETER_MANIFEST_INVALID" in readiness.blockers
    assert any("shadow_forward_start" in item for item in readiness.diagnostics)


def test_historical_sh25_readiness_builds_only_complete_locked_bundle() -> None:
    readiness = assess_historical_v25_evidence_readiness(
        symbol="DINO",
        market_csv=_market_csv(),
        tradingview_signal_csv=_signal_csv(),
        tradingview_bar_outcome_csv=_bar_outcome_csv(),
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-HISTORICAL-V25-V1",
        tradingview_source="TRADINGVIEW_EXPORT",
        tradingview_signal_revision="TV-V25-SIGNALS-V1",
        tradingview_bar_outcome_revision="TV-V25-BAR-OUTCOMES-V1",
    )

    assert readiness.ready_for_locked_reference is True
    assert readiness.blockers == ()
    assert readiness.locked_reference_id is not None
    assert readiness.parameter_manifest_state is EvidenceArtifactState.PRESENT
