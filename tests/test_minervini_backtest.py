from datetime import date, timedelta

from daily_alpha.backtest import Bar
from daily_alpha.minervini_backtest import build_features, market_regime, simulate


def bars(start: date, n: int, drift: float = 0.002, volume: float = 2_000_000) -> list[Bar]:
    out = []
    price = 50.0
    for i in range(n):
        price *= 1.0 + drift
        out.append(Bar(start + timedelta(days=i), price * 0.995, price * 1.01, price * 0.99, price, volume))
    return out


def test_market_regime_is_close_known():
    spy = bars(date(2020, 1, 1), 280)
    qqq = bars(date(2020, 1, 1), 280)
    regime = market_regime(spy, qqq)
    assert regime[spy[-1].trade_date] == 1.0


def test_features_do_not_use_future_bars():
    series = bars(date(2020, 1, 1), 320)
    benchmark = {b.trade_date: b for b in series}
    before = build_features(series, benchmark)
    extended = build_features(series + bars(series[-1].trade_date + timedelta(days=1), 10, drift=-0.03), benchmark)
    check_date = series[-1].trade_date
    assert before[check_date] == extended[check_date]


def test_simulation_without_signals_stays_in_cash():
    spy = bars(date(2020, 1, 1), 320)
    qqq = bars(date(2020, 1, 1), 320)
    regime = market_regime(spy, qqq)
    start, end = spy[250].trade_date, spy[-1].trade_date
    nav, trades, metrics = simulate(
        {"SPY": spy, "QQQ": qqq}, {}, regime,
        start=start, end=end, initial_nav=1_000_000.0,
    )
    assert trades == []
    assert metrics["ending_nav"] == 1_000_000.0
    assert nav
