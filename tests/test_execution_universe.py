from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from daily_alpha.backtest import Bar
from daily_alpha.execution_universe import (
    SCANNER_SOURCE,
    ScannerState,
    build_scanner_ingress,
    evaluate_latest_v24,
    select_execution_universe,
)


def _bars(count: int = 80, *, end: date = date(2026, 8, 17), close: float = 110.0):
    start = end - timedelta(days=count - 1)
    return [
        Bar(
            trade_date=start + timedelta(days=index),
            open=close - 1,
            high=close + 2,
            low=close - 2,
            close=close,
            volume=1_000_000,
            earnings_event=False,
        )
        for index in range(count)
    ]


def _rows(count: int, **latest):
    base = {
        "atr": 5.0,
        "rsi": 55.0,
        "adx": 30.0,
        "efficiency": 0.30,
        "upper20": 100.0,
        "lower10": 95.0,
        "fresh_breakout": False,
        "trend_state": 1,
        "bear_flip": False,
        "normal_trend_mature": True,
        "is_earnings_up_gap": False,
        "gap_go": False,
        "gap_go_early": False,
        "gap_crap": False,
        "gap_wait": False,
        "gap_pct": 0.0,
        "gap_atr": 0.0,
        "close_location": 0.8,
        "gap_retention": 0.0,
        "relative_volume": 1.0,
    }
    rows = [dict(base) for _ in range(count)]
    rows[-1].update(latest)
    return rows


def test_select_execution_universe_adds_state_and_open_positions(tmp_path: Path):
    shortlist = tmp_path / "shortlist.csv"
    shortlist.write_text(
        "rank,symbol,display_label\n"
        "3,CCC,LEADER\n"
        "1,AAA,EMERGING\n"
        "2,BBB,LEADER\n",
        encoding="utf-8",
    )
    state = {
        "OLD": ScannerState(
            symbol="OLD",
            entry_date="2026-08-14",
            runner_base_entry=50.0,
            runner_base_atr=2.0,
            entry_breakout_level=49.0,
        )
    }
    result = select_execution_universe(
        shortlist,
        state,
        open_symbols=["EXT"],
        limit=2,
    )
    assert result == ["AAA", "BBB", "OLD", "EXT"]


def test_build_scanner_ingress_is_paper_only_and_canonical():
    now = datetime(2026, 8, 17, 20, 20, tzinfo=UTC)
    signal = {
        "source": SCANNER_SOURCE,
        "signal_id": "DA-SCAN-MU-2026-08-17-ENTRY_LONG",
        "symbol": "MU",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "D",
        "price": 1000.0,
        "bar_time": now.isoformat(),
        "entry_type": "NORMAL_BREAKOUT",
        "earnings_gap_class": "NONE",
        "earnings_gap_pct": 0.0,
        "earnings_gap_atr": 0.0,
        "earnings_close_location": 0.0,
        "earnings_gap_retention": 0.0,
        "earnings_relative_volume": 1.0,
        "stock_stop_price": 950.0,
        "average_daily_dollar_volume": 500_000_000.0,
    }
    ingress = build_scanner_ingress(signal, received_at=now)
    assert ingress["source"] == SCANNER_SOURCE
    assert ingress["trading_authorized"] is False
    assert ingress["paper_execution_triggered"] is False
    assert ingress["live_trading_enabled"] is False


def test_build_scanner_ingress_rejects_webhook_secret():
    now = datetime(2026, 8, 17, 20, 20, tzinfo=UTC)
    signal = {
        "source": SCANNER_SOURCE,
        "webhook_secret": "must-not-be-here",
        "signal_id": "x",
        "symbol": "MU",
        "action": "EXIT",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "D",
        "price": 1000.0,
        "bar_time": now.isoformat(),
    }
    with pytest.raises(ValueError, match="webhook secret"):
        build_scanner_ingress(signal, received_at=now)


def test_flat_symbol_emits_v24_normal_entry(monkeypatch):
    bars = _bars(close=110.0)
    rows = _rows(
        len(bars),
        fresh_breakout=True,
        trend_state=1,
        normal_trend_mature=True,
        efficiency=0.35,
        rsi=60.0,
        adx=32.0,
        atr=5.0,
        upper20=105.0,
        lower10=98.0,
    )
    monkeypatch.setattr("daily_alpha.execution_universe.indicators", lambda _: rows)
    now = datetime(2026, 8, 17, 20, 20, tzinfo=UTC)
    decision = evaluate_latest_v24(
        "MU",
        bars,
        state=None,
        now=now,
        require_trade_date=date(2026, 8, 17),
    )
    assert decision.action == "ENTRY_LONG"
    assert decision.signal is not None
    assert decision.signal["entry_type"] == "NORMAL_BREAKOUT"
    assert decision.proposed_state is not None
    assert decision.proposed_state.runner_base_entry == 110.0
    assert decision.proposed_state.entry_breakout_level == 105.0


def test_open_symbol_prioritizes_v24_exit(monkeypatch):
    bars = _bars(close=90.0)
    rows = _rows(
        len(bars),
        lower10=95.0,
        fresh_breakout=False,
        trend_state=1,
        bear_flip=False,
    )
    monkeypatch.setattr("daily_alpha.execution_universe.indicators", lambda _: rows)
    state = ScannerState(
        symbol="MU",
        entry_date=bars[-5].trade_date.isoformat(),
        runner_base_entry=100.0,
        runner_base_atr=5.0,
        entry_breakout_level=99.0,
    )
    decision = evaluate_latest_v24(
        "MU",
        bars,
        state=state,
        now=datetime(2026, 8, 17, 20, 20, tzinfo=UTC),
        require_trade_date=date(2026, 8, 17),
    )
    assert decision.action == "EXIT"
    assert decision.reason == "TURTLE_EXIT"
    assert decision.proposed_state is None


def test_runner_harvest_sets_underlying_break_even(monkeypatch):
    bars = _bars(close=116.0)
    rows = _rows(len(bars), lower10=90.0, adx=35.0, trend_state=1)
    monkeypatch.setattr("daily_alpha.execution_universe.indicators", lambda _: rows)
    state = ScannerState(
        symbol="MU",
        entry_date=bars[-10].trade_date.isoformat(),
        runner_base_entry=100.0,
        runner_base_atr=5.0,
        entry_breakout_level=99.0,
        runner_stage="ADD_2_ATR",
        add1_price=106.0,
        add2_price=111.0,
    )
    decision = evaluate_latest_v24(
        "MU",
        bars,
        state=state,
        now=datetime(2026, 8, 17, 20, 20, tzinfo=UTC),
        require_trade_date=date(2026, 8, 17),
    )
    assert decision.action == "PARTIAL"
    assert decision.proposed_state is not None
    assert decision.proposed_state.runner_stage == "HARVEST_3_ATR"
    assert decision.proposed_state.break_even_level == pytest.approx((200 + 106 + 111) / 4)
