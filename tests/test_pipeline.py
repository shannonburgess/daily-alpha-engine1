from datetime import UTC, datetime

from daily_alpha.ledger import PaperLedger, TradeState
from daily_alpha.models import (
    Decision,
    DecisionStatus,
    InstrumentSelected,
    OptionCandidate,
)
from daily_alpha.pipeline import EntryPricing, PaperTradingPipeline
from daily_alpha.signals import SignalAction, parse_pine_signal
from daily_alpha.sizing import PortfolioLimits


NOW = datetime(2026, 8, 15, 16, 5, tzinfo=UTC)


def signal(action):
    return parse_pine_signal(
        {
            "signal_id": f"id-{action}",
            "symbol": "RDW",
            "action": action,
            "strategy": "QARS Turtle",
            "strategy_version": "1.0.0",
            "timeframe": "1D",
            "price": 15.25,
            "bar_time": "2026-08-15T16:00:00Z",
        },
        received_at=NOW,
    )


def test_option_entry_and_exit_use_option_ledger(tmp_path):
    ledger = PaperLedger(tmp_path)
    pipeline = PaperTradingPipeline(ledger, PortfolioLimits(nav=1_000_000))
    contract = OptionCandidate(
        symbol="RDW",
        expiration="2026-10-16",
        strike=15,
        option_type="CALL",
        dte=62,
        bid=1.9,
        ask=2.1,
        open_interest=500,
        volume=50,
    )
    decision = Decision.create(
        symbol="RDW",
        status=DecisionStatus.SELECTED,
        instrument_selected=InstrumentSelected.OPTION,
        fallback_reason="QUALIFIED_OPTION_SELECTED",
        selected_contract=contract,
    )

    opened = pipeline.process_entry(
        signal=signal(SignalAction.ENTRY_LONG),
        decision=decision,
        pricing=EntryPricing(option_premium=2.0),
    )
    closed = pipeline.process_exit(
        signal=signal(SignalAction.EXIT),
        option_exit_price=2.5,
    )

    assert opened.instrument == InstrumentSelected.OPTION
    assert closed[0].state == TradeState.CLOSED
    assert closed[0].realized_pnl == 1_250
    assert (tmp_path / "option_trades.jsonl").exists()
    assert not (tmp_path / "stock_trades.jsonl").exists()


def test_stock_fallback_has_separate_ledger(tmp_path):
    ledger = PaperLedger(tmp_path)
    pipeline = PaperTradingPipeline(ledger, PortfolioLimits(nav=1_000_000))
    decision = Decision.create(
        symbol="RDW",
        status=DecisionStatus.SELECTED,
        instrument_selected=InstrumentSelected.STOCK,
        fallback_reason="NO_OPTION_PASSED_QUALITY_FILTERS_STOCK_ELIGIBLE",
    )

    opened = pipeline.process_entry(
        signal=signal(SignalAction.ENTRY_LONG),
        decision=decision,
        pricing=EntryPricing(stock_price=15, stock_stop_price=14),
    )

    assert opened.instrument == InstrumentSelected.STOCK
    assert (tmp_path / "stock_trades.jsonl").exists()
    assert not (tmp_path / "option_trades.jsonl").exists()
