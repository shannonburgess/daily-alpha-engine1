import json
from datetime import UTC, datetime

from daily_alpha.pine_ingress import build_pine_ingress_record

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def test_entry_preserves_validated_stop_and_liquidity_without_secret():
    record = build_pine_ingress_record(
        {
            "body": json.dumps(
                {
                    "webhook_secret": "secret",
                    "signal_id": "entry-1",
                    "symbol": "AAPL",
                    "action": "ENTRY_LONG",
                    "strategy": "DA_TURTLE_ADAPTIVE_TREND",
                    "strategy_version": "1.9",
                    "timeframe": "1D",
                    "price": 110.0,
                    "bar_time": NOW.isoformat(),
                    "stock_stop_price": 100.0,
                    "average_daily_dollar_volume": 75_000_000.0,
                }
            )
        },
        expected_secret="secret",
        received_at=NOW,
    ).to_dict()

    assert record["schema_version"] == "2026-08-16-v4"
    assert record["stock_stop_price"] == 100.0
    assert record["average_daily_dollar_volume"] == 75_000_000.0
    assert record["entry_type"] is None
    assert "webhook_secret" not in record
