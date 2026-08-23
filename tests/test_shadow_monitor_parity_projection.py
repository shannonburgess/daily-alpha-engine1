import json

from daily_alpha.armed_replay import list_recent_pine_event_state


class _Client:
    def scan(self, **kwargs):
        ingress = {
            "source": "TRADINGVIEW_PINE",
            "signal_id": "NVDA-ENTRY-1",
            "symbol": "NVDA",
            "action": "ENTRY_LONG",
            "strategy": "DA_TURTLE_ADAPTIVE_TREND",
            "strategy_version": "2.5",
            "model_id": "PAPER_SHADOW_V25",
            "timeframe": "1D",
            "price": 201.25,
            "bar_time": "2026-08-21T20:00:00+00:00",
            "received_at": "2026-08-21T20:00:03+00:00",
            "entry_type": "ARMED_BREAKOUT_CONFIRM",
            "runner_stage": None,
            "position_fraction": None,
            "earnings_gap_class": "NONE",
            "stock_stop_price": 188.5,
            "average_daily_dollar_volume": 12_500_000_000,
            "breakout_level": 198.0,
            "armed_age": 2,
            "forward_test_start": "2026-08-19",
            "replay_max_price": 202.0,
        }
        execution = {
            "disposition": "NO_TRADE",
            "reason": "PORTFOLIO_CONTEXT_REQUIRED",
            "paper_execution_triggered": False,
            "paper_ledger_updated": False,
            "trading_authorized": False,
            "live_trading_enabled": False,
        }
        return {
            "ScannedCount": 1,
            "Items": [
                {
                    "signal_id": {"S": "NVDA-ENTRY-1"},
                    "symbol": {"S": "NVDA"},
                    "action": {"S": "ENTRY_LONG"},
                    "disposition": {"S": "NO_TRADE"},
                    "reason": {"S": "PORTFOLIO_CONTEXT_REQUIRED"},
                    "ingress_json": {"S": json.dumps(ingress)},
                    "execution_json": {"S": json.dumps(execution)},
                }
            ],
        }


class _Store:
    table_name = "paper-shadow-events"
    account_id = "paper-shadow"
    client = _Client()


def test_monitor_projects_exact_persisted_pine_fields_needed_for_forward_parity():
    state = list_recent_pine_event_state(_Store(), limit=10)

    event = state["events"][0]
    assert event["source"] == "TRADINGVIEW_PINE"
    assert event["strategy"] == "DA_TURTLE_ADAPTIVE_TREND"
    assert event["strategy_version"] == "2.5"
    assert event["model_id"] == "PAPER_SHADOW_V25"
    assert event["timeframe"] == "1D"
    assert event["price"] == 201.25
    assert event["bar_time"] == "2026-08-21T20:00:00+00:00"
    assert event["entry_type"] == "ARMED_BREAKOUT_CONFIRM"
    assert event["breakout_level"] == 198.0
    assert event["armed_age"] == 2
    assert event["replay_max_price"] == 202.0
    assert event["stock_stop_price"] == 188.5
    assert event["average_daily_dollar_volume"] == 12_500_000_000
    assert event["disposition"] == "NO_TRADE"
    assert event["reason"] == "PORTFOLIO_CONTEXT_REQUIRED"
    assert event["paper_execution_triggered"] is False
    assert event["trading_authorized"] is False
    assert event["live_trading_enabled"] is False


def test_monitor_projection_does_not_expose_webhook_secret():
    state = list_recent_pine_event_state(_Store(), limit=10)
    event = state["events"][0]
    assert "webhook_secret" not in event
