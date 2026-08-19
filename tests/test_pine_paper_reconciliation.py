from datetime import UTC, datetime

import pytest

from daily_alpha.pine_paper_reconciliation import ReconciledAwsPinePaperExecutor


class EmptyLedger:
    account_id = "paper-test"

    def find_open(self, symbol, instrument=None):
        return []


def _executor():
    return ReconciledAwsPinePaperExecutor(
        ledger=EmptyLedger(),
        secrets_client=object(),
        paper_nav=1_000_000,
        orats_factory=lambda token: None,
    )


def _entry_signal():
    return {
        "signal_id": "AMD-ENTRY-1",
        "symbol": "AMD",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 250.0,
        "bar_time": "2026-08-18T20:00:00+00:00",
        "sector": "Information Technology",
        "stock_stop_price": 235.0,
        "average_daily_dollar_volume": 1_000_000_000,
    }


def test_after_hours_entry_is_armed_for_next_tradable_window():
    result = _executor().execute(
        _entry_signal(),
        now=datetime(2026, 8, 18, 20, 5, tzinfo=UTC),
    )

    assert result["disposition"] == "ARMED_FOR_NEXT_TRADABLE_WINDOW"
    assert result["reason"] == "MARKET_CLOSED_REVALIDATION_REQUIRED"
    assert result["paper_execution_triggered"] is False
    assert result["paper_ledger_updated"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert result["context"]["revalidation_required"] is True
    assert result["context"]["refresh_orats"] is True
    assert result["context"]["refresh_portfolio_risk"] is True
    assert result["context"]["refresh_no_chase"] is True


@pytest.mark.parametrize(
    ("action", "runner_stage"),
    [
        ("ADD", "ADD_1_ATR"),
        ("PARTIAL", "HARVEST_3_ATR"),
        ("EXIT", None),
    ],
)
def test_orphan_runner_signal_is_explicit_state_mismatch(action, runner_stage):
    ingress = {
        "signal_id": f"VLO-{action}-1",
        "symbol": "VLO",
        "action": action,
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 350.05,
        "bar_time": "2026-08-18T20:00:00+00:00",
    }
    if runner_stage is not None:
        ingress["runner_stage"] = runner_stage
        ingress["position_fraction"] = 0.25

    result = _executor().execute(
        ingress,
        now=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
    )

    assert result["disposition"] == "STATE_MISMATCH"
    assert result["reason"] == "TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER"
    assert result["paper_execution_triggered"] is False
    assert result["paper_ledger_updated"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert result["context"]["orphan_action"] == action
    assert result["context"]["replay_allowed"] is False
