from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from daily_alpha.backtest import Bar
from daily_alpha.continuation_entry import (
    CONTINUATION_ENTRY_VARIANT,
    CONTINUATION_LIFECYCLE,
    evaluate_active_buy_continuation,
)


def _bars(count: int = 80, *, close: float = 23.0) -> list[Bar]:
    end = date(2026, 8, 20)
    start = end - timedelta(days=count - 1)
    return [
        Bar(
            trade_date=start + timedelta(days=index),
            open=close - 0.3,
            high=close + 0.5,
            low=close - 0.5,
            close=close,
            volume=3_000_000,
            earnings_event=False,
        )
        for index in range(count)
    ]


def _rows(count: int) -> list[dict]:
    base = {
        "atr": 2.0,
        "rsi": 60.0,
        "adx": 30.0,
        "efficiency": 0.30,
        "upper20": 22.0,
        "lower10": 20.0,
        "fresh_breakout": False,
        "trend_state": 1,
        "normal_trend_mature": True,
        "is_earnings_up_gap": False,
    }
    return [dict(base) for _ in range(count)]


def test_active_buy_recent_breakout_can_continue_below_frozen_pine_25_floor(monkeypatch):
    bars = _bars(close=23.0)
    rows = _rows(len(bars))
    rows[-3]["fresh_breakout"] = True
    rows[-3]["upper20"] = 22.0
    rows[-3]["atr"] = 2.0
    monkeypatch.setattr("daily_alpha.continuation_entry.indicators", lambda _: rows)

    decision = evaluate_active_buy_continuation(
        "PR",
        bars,
        ovtlyr_status="ACTIVE_BUY",
        state=None,
        now=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
        require_trade_date=date(2026, 8, 20),
    )

    assert decision.action == "ENTRY_LONG"
    assert decision.reason == CONTINUATION_ENTRY_VARIANT
    assert decision.signal is not None
    assert decision.signal["entry_variant"] == CONTINUATION_ENTRY_VARIANT
    assert decision.signal["lifecycle"] == CONTINUATION_LIFECYCLE
    assert decision.signal["source_lifecycle"] == "ACTIVE_BUY"
    assert decision.signal["replay_max_price"] == 24.0
    assert decision.proposed_state is not None
    assert decision.proposed_state.entry_breakout_level == 22.0


def test_active_buy_continuation_rejects_chase_above_one_atr(monkeypatch):
    bars = _bars(close=24.5)
    rows = _rows(len(bars))
    rows[-2]["fresh_breakout"] = True
    rows[-2]["upper20"] = 22.0
    rows[-2]["atr"] = 2.0
    monkeypatch.setattr("daily_alpha.continuation_entry.indicators", lambda _: rows)

    decision = evaluate_active_buy_continuation(
        "PR",
        bars,
        ovtlyr_status="ACTIVE_BUY",
        state=None,
        now=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert decision.action is None
    assert decision.reason == "WAIT_ACTIVE_BUY_EXTENDED_ABOVE_1ATR"


def test_active_buy_continuation_requires_recent_breakout(monkeypatch):
    bars = _bars(close=23.0)
    rows = _rows(len(bars))
    rows[-12]["fresh_breakout"] = True
    monkeypatch.setattr("daily_alpha.continuation_entry.indicators", lambda _: rows)

    decision = evaluate_active_buy_continuation(
        "PR",
        bars,
        ovtlyr_status="ACTIVE_BUY",
        state=None,
        now=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert decision.action is None
    assert decision.reason == "WAIT_ACTIVE_BUY_NO_RECENT_20D_BREAKOUT"


def test_continuation_is_not_applied_to_non_active_buy(monkeypatch):
    bars = _bars(close=23.0)
    rows = _rows(len(bars))
    rows[-2]["fresh_breakout"] = True
    monkeypatch.setattr("daily_alpha.continuation_entry.indicators", lambda _: rows)

    decision = evaluate_active_buy_continuation(
        "PR",
        bars,
        ovtlyr_status="LEADER",
        state=None,
        now=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert decision.action is None
    assert decision.reason == "CONTINUATION_REQUIRES_ACTIVE_BUY"


def test_continuation_still_respects_daily_alpha_10_floor(monkeypatch):
    bars = _bars(close=9.5)
    rows = _rows(len(bars))
    rows[-2]["fresh_breakout"] = True
    rows[-2]["upper20"] = 9.0
    rows[-2]["atr"] = 1.0
    monkeypatch.setattr("daily_alpha.continuation_entry.indicators", lambda _: rows)

    decision = evaluate_active_buy_continuation(
        "LOW",
        bars,
        ovtlyr_status="ACTIVE_BUY",
        state=None,
        now=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert decision.action is None
    assert decision.reason == "WAIT_ACTIVE_BUY_PRICE_BELOW_10"
