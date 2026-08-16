from datetime import UTC, datetime, timedelta

from daily_alpha.runtime import evaluate_entry_event

NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


def base_event():
    return {
        "operation": "EVALUATE_ENTRY",
        "signal": {
            "signal_id": "sig-aapl-1",
            "symbol": "AAPL",
            "action": "ENTRY_LONG",
            "strategy": "DAILY_ALPHA_PINE",
            "strategy_version": "v1",
            "timeframe": "1D",
            "price": 220.0,
            "bar_time": (NOW - timedelta(minutes=2)).isoformat(),
        },
        "portfolio": {
            "snapshot_id": "portfolio-1",
            "account_id": "paper-staging",
            "source": "TEST",
            "as_of": NOW.isoformat(),
            "cash": 1_000_000.0,
            "buying_power": 1_000_000.0,
            "positions": [],
            "data_status": "AVAILABLE",
        },
        "risk_state": {},
        "proposed_trade": {
            "planned_loss": 3_000.0,
            "cluster_id": "MEGA_CAP_TECH",
            "sector": "TECHNOLOGY",
            "liquidity_score": 0.95,
        },
        "market": {
            "option_data_available": True,
            "option_data_observed_at": (NOW - timedelta(minutes=5)).isoformat(),
            "orats_mode": "delayed",
            "options": [
                {
                    "expiration": "2026-10-16",
                    "strike": 220.0,
                    "option_type": "CALL",
                    "dte": 60,
                    "bid": 5.00,
                    "ask": 5.20,
                    "open_interest": 1000,
                    "volume": 200,
                    "delta": 0.50,
                }
            ],
            "stock": {
                "price": 220.0,
                "average_daily_dollar_volume": 5_000_000_000.0,
                "eligible": True,
            },
        },
    }


def test_qualified_option_is_selected_after_risk_approval():
    result = evaluate_entry_event(base_event(), now=NOW)
    assert result["risk"]["status"] == "APPROVED"
    assert result["decision"]["status"] == "SELECTED"
    assert result["decision"]["instrument_selected"] == "OPTION"
    assert result["decision"]["fallback_reason"] == "QUALIFIED_OPTION_SELECTED"
    assert result["paper_trade_written"] is False
    assert result["live_trading_enabled"] is False


def test_valid_orats_data_can_fall_back_to_liquid_stock():
    event = base_event()
    event["market"]["options"][0]["open_interest"] = 5
    result = evaluate_entry_event(event, now=NOW)
    assert result["decision"]["status"] == "SELECTED"
    assert result["decision"]["instrument_selected"] == "STOCK"
    assert result["decision"]["fallback_reason"] == (
        "NO_OPTION_PASSED_QUALITY_FILTERS_STOCK_ELIGIBLE"
    )


def test_stale_orats_data_never_authorizes_stock_fallback():
    event = base_event()
    event["market"]["option_data_observed_at"] = (NOW - timedelta(hours=1)).isoformat()
    result = evaluate_entry_event(event, now=NOW)
    assert result["decision"]["status"] == "DATA_ERROR"
    assert result["decision"]["instrument_selected"] == "NONE"
    assert result["decision"]["fallback_reason"] == "ORATS_DATA_UNAVAILABLE_OR_STALE"


def test_risk_rejection_happens_before_orats_is_required():
    event = base_event()
    event["proposed_trade"]["planned_loss"] = 20_000.0
    del event["market"]
    result = evaluate_entry_event(event, now=NOW)
    assert result["risk"]["status"] == "REJECTED"
    assert "POSITION_RISK_LIMIT" in result["risk"]["reasons"]
    assert result["decision"]["status"] == "NO_TRADE"
    assert result["decision"]["fallback_reason"] == "PORTFOLIO_RISK_GATE_FAILED"
    assert result["option_data_checked"] is False
