import json
from dataclasses import asdict
from datetime import datetime

import pytest

from daily_alpha.pine_parameter_manifest import PineParameterManifestError
from daily_alpha.pine_v25_historical_reference import (
    build_historical_v25_reference,
    evaluate_historical_v25_reference,
)
from daily_alpha.pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_BLOB_SHA,
    PINE_V25_STRATEGY_VERSION,
    V25Parameters,
)

MARKET_CSV = (
    "time,symbol,open,high,low,close,volume,earnings_state,earnings_actual,"
    "earnings_known_at,source_id\n"
    "2026-08-20T20:00:00+00:00,ABC,100,101,99,100.5,2000000,NONE,,,mkt-1\n"
    "2026-08-21T20:00:00+00:00,ABC,100.5,102,100,101.5,2100000,NONE,,,mkt-2\n"
)
SIGNAL_CSV = (
    "bar_time,symbol,action,price,entry_type,runner_stage,quantity_units,source_id\n"
)
OUTCOME_CSV = (
    "bar_time,symbol,outcome_kind,signal_actions,rejection_reasons,entry_type,source_id\n"
    "2026-08-20T20:00:00+00:00,ABC,NO_TRADE,,,NONE,out-1\n"
    "2026-08-21T20:00:00+00:00,ABC,NO_TRADE,,,NONE,out-2\n"
)


def _manifest(**overrides: object) -> str:
    parameters = asdict(V25Parameters())
    for key, value in tuple(parameters.items()):
        if isinstance(value, datetime):
            parameters[key] = value.isoformat()
    payload: dict[str, object] = {
        "model_id": PINE_V25_MODEL_ID,
        "strategy_version": PINE_V25_STRATEGY_VERSION,
        "source_blob_sha": PINE_V25_SOURCE_BLOB_SHA,
        "process_orders_on_close": True,
        "parameters": parameters,
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True)


def _build(parameter_manifest_json: str | None = None):
    return build_historical_v25_reference(
        symbol="ABC",
        market_csv=MARKET_CSV,
        tradingview_signal_csv=SIGNAL_CSV,
        tradingview_bar_outcome_csv=OUTCOME_CSV,
        parameter_manifest_json=parameter_manifest_json or _manifest(),
        market_source="POINT_IN_TIME_MARKET_EXPORT",
        market_revision="market-r1",
        tradingview_source="TRADINGVIEW",
        tradingview_signal_revision="signals-r1",
        tradingview_bar_outcome_revision="outcomes-r1",
    )


def test_v25_history_requires_explicit_no_trade_rows_and_exact_parameters() -> None:
    reference = _build()
    evaluation = evaluate_historical_v25_reference(reference)

    assert evaluation.exact is True
    assert evaluation.signal_report.reference_count == 0
    assert evaluation.signal_report.python_count == 0
    assert evaluation.bar_outcome_report.reference_count == 2
    assert evaluation.bar_outcome_report.exact_bar_count == 2
    assert reference.parameter_manifest.parameters == V25Parameters()
    assert len(reference.reference_id) == 64


def test_v25_history_rejects_v24_model_identity() -> None:
    with pytest.raises(PineParameterManifestError, match="PARAMETER_MODEL_ID_MISMATCH"):
        _build(_manifest(model_id="PAPER_SHADOW_V24"))


def test_v25_history_rejects_missing_shadow_forward_parameter() -> None:
    payload = json.loads(_manifest())
    del payload["parameters"]["shadow_forward_start"]

    with pytest.raises(PineParameterManifestError, match="PARAMETER_FIELDS_MISMATCH"):
        _build(json.dumps(payload, sort_keys=True))


def test_v25_history_rejects_process_orders_on_close_false() -> None:
    with pytest.raises(
        PineParameterManifestError,
        match="PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE",
    ):
        _build(_manifest(process_orders_on_close=False))
