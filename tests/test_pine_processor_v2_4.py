from datetime import UTC, datetime, timedelta

from daily_alpha.pine_processor import process_ingress_record

NOW = datetime(2026, 8, 16, 23, 40, tzinfo=UTC)
RECEIVED = NOW - timedelta(minutes=2)


def test_processor_accepts_v2_4_v4_ingress_during_migration():
    payload = {
        "schema_version": "2026-08-16-v4",
        "source": "TRADINGVIEW_PINE",
        "signal_id": "mrvl-gap-go-processor-1",
        "symbol": "MRVL",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "D",
        "price": 89.57,
        "bar_time": (RECEIVED - timedelta(minutes=1)).isoformat(),
        "received_at": RECEIVED.isoformat(),
        "position_fraction": None,
        "runner_stage": None,
        "entry_type": "EARNINGS_GAP_GO",
        "earnings_gap_class": "EARNINGS_GAP_GO",
        "earnings_gap_pct": 12.0,
        "earnings_gap_atr": 2.1,
        "earnings_close_location": 0.84,
        "earnings_gap_retention": 1.15,
        "earnings_relative_volume": 2.4,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }

    result = process_ingress_record(payload, now=NOW)

    assert result.disposition == "HELD_FOR_CONTEXT"
    assert result.reason == "ENTRY_REQUIRES_SERVER_PORTFOLIO_RISK_CONTEXT"
    assert "ORATS" not in result.reason
