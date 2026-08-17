import json
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.pine_ingress import PineIngressError, build_pine_ingress_record

NOW = datetime(2026, 8, 16, 23, 30, tzinfo=UTC)
SECRET = "earnings-gap-test-secret"


def _payload(**overrides):
    payload = {
        "webhook_secret": SECRET,
        "signal_id": "mrvl-gap-go-1",
        "symbol": "MRVL",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "D",
        "price": 89.57,
        "bar_time": (NOW - timedelta(minutes=2)).isoformat(),
        "entry_type": "EARNINGS_GAP_GO",
        "earnings_gap_class": "EARNINGS_GAP_GO",
        "earnings_gap_pct": 12.0,
        "earnings_gap_atr": 2.1,
        "earnings_close_location": 0.84,
        "earnings_gap_retention": 1.15,
        "earnings_relative_volume": 2.4,
        "stock_stop_price": 78.0,
        "average_daily_dollar_volume": 1_200_000_000.0,
    }
    payload.update(overrides)
    return payload


def test_v2_4_gap_go_metadata_is_normalized_and_preserved():
    record = build_pine_ingress_record(
        {"body": json.dumps(_payload())},
        expected_secret=SECRET,
        received_at=NOW,
    )
    data = record.to_dict()

    assert data["schema_version"] == "2026-08-16-v4"
    assert data["entry_type"] == "EARNINGS_GAP_GO"
    assert data["earnings_gap_class"] == "EARNINGS_GAP_GO"
    assert data["earnings_gap_pct"] == 12.0
    assert data["earnings_relative_volume"] == 2.4


def test_v2_4_entry_requires_entry_type():
    with pytest.raises(PineIngressError, match="entry_type is required"):
        build_pine_ingress_record(
            {"body": json.dumps(_payload(entry_type=None))},
            expected_secret=SECRET,
            received_at=NOW,
        )


def test_gap_go_requires_matching_classification():
    with pytest.raises(PineIngressError, match="matching earnings_gap_class"):
        build_pine_ingress_record(
            {"body": json.dumps(_payload(earnings_gap_class="EARNINGS_WAIT"))},
            expected_secret=SECRET,
            received_at=NOW,
        )


def test_early_watch_cannot_be_submitted_as_entry_type():
    with pytest.raises(PineIngressError, match="entry_type is invalid"):
        build_pine_ingress_record(
            {
                "body": json.dumps(
                    _payload(
                        entry_type="EARNINGS_GAP_GO_EARLY",
                        earnings_gap_class="EARNINGS_GAP_GO_EARLY",
                        earnings_close_location=0.65,
                    )
                )
            },
            expected_secret=SECRET,
            received_at=NOW,
        )


def test_v2_3_entry_remains_backward_compatible_without_event_metadata():
    payload = _payload(
        strategy_version="2.3",
        entry_type=None,
        earnings_gap_class=None,
        earnings_gap_pct=None,
        earnings_gap_atr=None,
        earnings_close_location=None,
        earnings_gap_retention=None,
        earnings_relative_volume=None,
    )
    record = build_pine_ingress_record(
        {"body": json.dumps(payload)},
        expected_secret=SECRET,
        received_at=NOW,
    )

    assert record.strategy_version == "2.3"
    assert record.entry_type is None
