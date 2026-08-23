import json
from dataclasses import asdict
from datetime import datetime

import pytest

from daily_alpha.pine_historical_reference_locked import (
    build_locked_historical_v24_reference,
    evaluate_locked_historical_v24_reference,
)
from daily_alpha.pine_parameter_manifest import PineParameterManifestError
from daily_alpha.pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_STRATEGY_VERSION,
    V24Parameters,
)

MARKET_CSV = (
    "time,symbol,open,high,low,close,volume,earnings_state,earnings_actual,"
    "earnings_known_at,source_id\n"
    "2026-01-02T21:00:00+00:00,ABC,100,101,99,100.5,2000000,NONE,,,mkt-1\n"
    "2026-01-05T21:00:00+00:00,ABC,100.5,102,100,101.5,2100000,NONE,,,mkt-2\n"
)
SIGNAL_CSV = (
    "bar_time,symbol,action,price,entry_type,runner_stage,quantity_units,source_id\n"
)
OUTCOME_CSV = (
    "bar_time,symbol,outcome_kind,signal_actions,rejection_reasons,entry_type,source_id\n"
    "2026-01-02T21:00:00+00:00,ABC,NO_TRADE,,,NONE,out-1\n"
    "2026-01-05T21:00:00+00:00,ABC,NO_TRADE,,,NONE,out-2\n"
)


def _manifest(**overrides: object) -> str:
    parameters = asdict(V24Parameters())
    for key, value in tuple(parameters.items()):
        if isinstance(value, datetime):
            parameters[key] = value.isoformat()
    payload: dict[str, object] = {
        "model_id": PINE_V24_MODEL_ID,
        "strategy_version": PINE_V24_STRATEGY_VERSION,
        "source_blob_sha": PINE_V24_SOURCE_BLOB_SHA,
        "process_orders_on_close": True,
        "parameters": parameters,
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True)


def _build(parameter_manifest_json: str | None = None):
    return build_locked_historical_v24_reference(
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


def test_locked_history_uses_hashed_complete_parameter_manifest() -> None:
    reference = _build()
    evaluation = evaluate_locked_historical_v24_reference(reference)

    assert evaluation.exact is True
    assert evaluation.reference_id == reference.reference_id
    assert len(reference.parameter_manifest.sha256) == 64
    assert reference.parameter_manifest.process_orders_on_close is True
    assert reference.parameter_manifest.parameters == V24Parameters()


def test_locked_history_rejects_wrong_frozen_source_blob() -> None:
    with pytest.raises(
        PineParameterManifestError,
        match="PARAMETER_SOURCE_BLOB_SHA_MISMATCH",
    ):
        _build(_manifest(source_blob_sha="wrong"))


def test_locked_history_rejects_process_orders_on_close_false() -> None:
    with pytest.raises(
        PineParameterManifestError,
        match="PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE",
    ):
        _build(_manifest(process_orders_on_close=False))


def test_locked_history_rejects_incomplete_parameter_export() -> None:
    payload = json.loads(_manifest())
    del payload["parameters"]["min_adx"]

    with pytest.raises(PineParameterManifestError, match="PARAMETER_FIELDS_MISMATCH"):
        _build(json.dumps(payload, sort_keys=True))
