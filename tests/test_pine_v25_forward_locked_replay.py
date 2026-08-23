import dataclasses
import json
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardParityDeploymentEvidence,
    ForwardPersistedEventEvidence,
)
from daily_alpha.pine_v25_forward_locked_replay import evaluate_locked_forward_v25_reference
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
    rows = [
        "time,symbol,open,high,low,close,volume,earnings_state,earnings_actual,earnings_known_at,source_id"
    ]
    for index in range(days):
        bar_time = BASE + timedelta(days=index)
        rows.append(
            f"{bar_time.isoformat()},DINO,100,101,99,100,2000000,NONE,,,DINO-{index}"
        )
    return "\n".join(rows) + "\n"


def _event(bar_time: datetime) -> ForwardPersistedEventEvidence:
    fields = {
        "signal_id": "DINO-FORWARD-V25-ENTRY",
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.5",
        "model_id": "PAPER_SHADOW_V25",
        "timeframe": "1D",
        "price": 100.0,
        "bar_time": bar_time.isoformat(),
        "entry_type": "NORMAL_BREAKOUT",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V25",
        signal_id="DINO-FORWARD-V25-ENTRY",
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
        scan_items_evaluated=len(events),
        open_count=0,
        armed_count_visible=0,
        events=tuple(events),
    )


def _deployment(events=()) -> ForwardParityDeploymentEvidence:
    return ForwardParityDeploymentEvidence(
        repository="shannonburgess/daily-alpha-engine1",
        commit_sha="c" * 40,
        workflow_run_id="32651982887",
        workflow_run_attempt="1",
        processor_version="50",
        processor_code_sha256="processor-code-hash",
        sh24=_book("PAPER_SHADOW_V24"),
        sh25=_book("PAPER_SHADOW_V25", events),
    )


def test_locked_v25_builder_replays_exact_market_and_parameter_artifacts() -> None:
    locked = evaluate_locked_forward_v25_reference(
        deployment=_deployment(),
        symbol="DINO",
        market_csv=_market_csv(),
        parameter_manifest_json=_manifest(),
        market_source="POINT_IN_TIME_DAILY_OHLCV",
        market_revision="DINO-2026-08-23-v25",
        python_engine_revision="pine_v25_parity.py@test",
    )

    assert locked.replay_inputs_locked is True
    assert locked.exact is True
    assert locked.report.reference_count == 0
    assert locked.report.python_count == 0
    assert locked.market_artifact.row_count == 35
    assert locked.replay_provenance.replay_bar_count == 35
    assert locked.replay_provenance.market_evidence_sha256 == locked.market_artifact.sha256
    assert locked.replay_provenance.parameter_manifest_sha256 == locked.parameter_manifest.sha256
    assert locked.replay_provenance.deployment_commit_sha == "c" * 40


def test_locked_v25_builder_requires_receipt_event_bar_in_market_evidence() -> None:
    missing_bar = BASE + timedelta(days=60)
    with pytest.raises(ValueError, match="absent from locked market evidence"):
        evaluate_locked_forward_v25_reference(
            deployment=_deployment((_event(missing_bar),)),
            symbol="DINO",
            market_csv=_market_csv(),
            parameter_manifest_json=_manifest(),
            market_source="POINT_IN_TIME_DAILY_OHLCV",
            market_revision="DINO-2026-08-23-v25",
            python_engine_revision="pine_v25_parity.py@test",
        )


def test_locked_v25_builder_requires_complete_shadow_forward_start_setting() -> None:
    payload = json.loads(_manifest())
    del payload["parameters"]["shadow_forward_start"]
    with pytest.raises(ValueError, match="PARAMETER_MANIFEST_FIELD_MISMATCH"):
        evaluate_locked_forward_v25_reference(
            deployment=_deployment(),
            symbol="DINO",
            market_csv=_market_csv(),
            parameter_manifest_json=json.dumps(payload),
            market_source="POINT_IN_TIME_DAILY_OHLCV",
            market_revision="DINO-2026-08-23-v25",
            python_engine_revision="pine_v25_parity.py@test",
        )


def test_locked_v25_builder_requires_process_orders_on_close_true() -> None:
    payload = json.loads(_manifest())
    payload["process_orders_on_close"] = False
    with pytest.raises(ValueError, match="PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE"):
        evaluate_locked_forward_v25_reference(
            deployment=_deployment(),
            symbol="DINO",
            market_csv=_market_csv(),
            parameter_manifest_json=json.dumps(payload),
            market_source="POINT_IN_TIME_DAILY_OHLCV",
            market_revision="DINO-2026-08-23-v25",
            python_engine_revision="pine_v25_parity.py@test",
        )
