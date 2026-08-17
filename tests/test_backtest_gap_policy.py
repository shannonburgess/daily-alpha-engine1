from datetime import date

from daily_alpha.backtest import (
    Bar,
    gap_go_close_location_band,
    run_strategy,
)
from daily_alpha.backtest_sensitivity import reclassify_gap_go


def _event_row(*, gap_go: bool, gap_go_early: bool) -> dict[str, object]:
    return {
        "atr": 5.0,
        "rsi": 60.0,
        "adx": 30.0,
        "efficiency": 0.40,
        "upper20": 95.0,
        "lower10": 90.0,
        "fresh_breakout": True,
        "trend_state": 1,
        "bear_flip": False,
        "normal_trend_mature": True,
        "earnings_window": True,
        "gap_dollars": 10.0,
        "gap_pct": 10.0,
        "gap_atr": 2.0,
        "close_location": 0.65 if gap_go_early else 0.70,
        "gap_retention": 1.0,
        "relative_volume": 2.0,
        "is_earnings_up_gap": True,
        "gap_go": gap_go,
        "gap_go_early": gap_go_early,
        "gap_crap": False,
        "gap_wait": False,
    }


def test_canonical_close_location_boundary_is_70_percent():
    assert gap_go_close_location_band(0.70) == "FULL"
    assert gap_go_close_location_band(0.699999) == "EARLY"
    assert gap_go_close_location_band(0.60) == "EARLY"
    assert gap_go_close_location_band(0.599999) == "BELOW"


def test_early_band_is_reported_but_never_authorizes_v24_entry():
    bar = Bar(
        trade_date=date(2026, 3, 6),
        open=96.0,
        high=104.0,
        low=94.0,
        close=100.0,
        volume=2_000_000,
        earnings_event=True,
    )

    trades, events = run_strategy(
        [bar],
        [_event_row(gap_go=False, gap_go_early=True)],
        version="2.4",
        start=bar.trade_date,
        end=bar.trade_date,
    )

    assert trades == []
    assert events[0]["classification"] == "EARNINGS_GAP_GO_EARLY"
    assert events[0]["v24_entry"] is False


def test_full_band_remains_v24_entry_eligible():
    bar = Bar(
        trade_date=date(2026, 3, 6),
        open=96.0,
        high=104.0,
        low=94.0,
        close=100.0,
        volume=2_000_000,
        earnings_event=True,
    )

    trades, events = run_strategy(
        [bar],
        [_event_row(gap_go=True, gap_go_early=False)],
        version="2.4",
        start=bar.trade_date,
        end=bar.trade_date,
    )

    assert len(trades) == 1
    assert trades[0].entry_type == "EARNINGS_GAP_GO"
    assert events[0]["classification"] == "EARNINGS_GAP_GO"
    assert events[0]["v24_entry"] is True


def test_sensitivity_runner_can_still_promote_65_percent_under_explicit_override():
    bar = Bar(
        trade_date=date(2026, 3, 6),
        open=96.0,
        high=104.0,
        low=94.0,
        close=100.0,
        volume=2_000_000,
        earnings_event=True,
    )
    row = _event_row(gap_go=False, gap_go_early=True)

    adjusted = reclassify_gap_go([bar], [row], close_location=0.60)

    assert adjusted[0]["gap_go"] is True
