import json

from daily_alpha.buy_continuity import (
    build_buy_continuity,
    write_buy_continuity_output,
)


def _write_universe(root, date, rows):
    run = root / date
    run.mkdir(parents=True)
    (run / "universe.csv").write_text(
        "Ticker,Signal,Sector,Industry,Trend,Momentum,Optionable,Partial Data Stocks\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_buy_continuity_tracks_streak_change_and_explicit_ineligibility(tmp_path):
    history = tmp_path / "history"
    _write_universe(
        history,
        "2026-08-17",
        [
            "AAA,Buy,Technology,Software,Up,Rising,Yes,No",
            "BBB,Buy,Industrials,Machinery,Up,Rising,Yes,No",
            "CCC,Buy,Energy,Oil & Gas,Up,Rising,Yes,No",
        ],
    )
    _write_universe(
        history,
        "2026-08-18",
        [
            "AAA,Buy,Technology,Software,Up,Rising,Yes,No",
            "BBB,Buy,Industrials,Machinery,Up,Rising,Yes,No",
            "CCC,Buy,Energy,Oil & Gas,Up,Rising,Yes,No",
        ],
    )
    _write_universe(
        history,
        "2026-08-19",
        [
            "AAA,Buy,Technology,Software,Up,Accelerating,Yes,No",
            "BBB,Buy,Industrials,Machinery,Up,Rising,No,No",
            "DDD,Sell,Health Care,Biotechnology,Down,Falling,Yes,No",
        ],
    )

    states = {state.symbol: state for state in build_buy_continuity(history)}

    aaa = states["AAA"]
    assert aaa.active_buy is True
    assert aaa.first_seen_date == "2026-08-17"
    assert aaa.first_buy_date == "2026-08-17"
    assert aaa.current_buy_streak_start == "2026-08-17"
    assert aaa.consecutive_buy_observations == 3
    assert aaa.total_buy_observations == 3
    assert aaa.last_meaningful_change_date == "2026-08-19"
    assert aaa.research_eligibility == "ACTIVE_BUY_ELIGIBLE"

    bbb = states["BBB"]
    assert bbb.active_buy is True
    assert bbb.consecutive_buy_observations == 3
    assert bbb.research_eligibility == "ACTIVE_BUY_NOT_OPTIONABLE"
    assert bbb.last_meaningful_change_date == "2026-08-19"

    ccc = states["CCC"]
    assert ccc.active_buy is False
    assert ccc.current_signal == "MISSING"
    assert ccc.consecutive_buy_observations == 0
    assert ccc.research_eligibility == "SYMBOL_MISSING_FROM_CURRENT_UNIVERSE"

    ddd = states["DDD"]
    assert ddd.active_buy is False
    assert ddd.first_buy_date is None
    assert ddd.research_eligibility == "SIGNAL_NO_LONGER_BUY"

    output = write_buy_continuity_output(tmp_path / "buy_continuity.json", tuple(states.values()))
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["active_buy"] == 2
    assert payload["summary"]["eligible_active_buy"] == 1
    assert payload["summary"]["trading_authorized"] is False
    assert payload["summary"]["live_trading_enabled"] is False
