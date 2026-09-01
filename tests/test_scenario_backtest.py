from datetime import date, timedelta

from daily_alpha.backtest import Bar
from daily_alpha.scenario_backtest import r2_scores, throttle_multiplier


def test_throttle_bands():
    assert throttle_multiplier(0.00) == (1.0, True)
    assert throttle_multiplier(0.06) == (0.75, True)
    assert throttle_multiplier(0.09) == (0.50, False)
    assert throttle_multiplier(0.13) == (0.25, False)
    assert throttle_multiplier(0.16) == (0.0, False)


def test_rank_scores_are_point_in_time():
    start = date(2025, 1, 1)
    bars = [
        Bar(start + timedelta(days=i), 100 + i, 101 + i, 99 + i, 100 + i, 1_000_000)
        for i in range(90)
    ]
    scores = r2_scores(bars)
    assert len(scores) == len(bars)
    assert scores[bars[40].trade_date] > 0
