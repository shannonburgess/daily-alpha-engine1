from __future__ import annotations

from datetime import UTC, datetime

from scripts.nyse_session_calendar import core_session_for
from scripts.shadow_monitor import render_markdown, summarize


def _book() -> dict:
    return {
        "open_count": 0,
        "open_positions": [],
        "armed_count_visible": 0,
        "armed_limit": 25,
        "armed_limit_reached": False,
        "armed_signals": [],
        "events": [],
        "event_count_visible": 0,
        "event_limit": 100,
        "scan_truncated": False,
    }


def _state() -> dict:
    return {
        "ok": True,
        "books": {
            "PAPER_SHADOW_V24": _book(),
            "PAPER_SHADOW_V25": _book(),
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def test_weekday_nyse_holiday_is_not_misdiagnosed_as_zero_trade_session() -> None:
    # Friday, July 3, 2026 is the NYSE Independence Day observed closure.
    now = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)
    summary = summarize(_state(), now=now)

    assert summary["session_phase"] == "NON_TRADING_DAY"
    assert summary["session_complete"] is False
    assert summary["zero_trade_status"] == "NON_TRADING_DAY"
    assert summary["market_session_calendar"]["closure_reason"] == (
        "INDEPENDENCE_DAY_OBSERVED"
    )
    assert summary["diagnosis"] == "NO_GENUINE_STRATEGY_EVENT_RECEIVED"
    rendered = render_markdown(summary)
    assert "verified NYSE calendar marks this ET date as a non-trading day" in rendered
    assert "final zero-trade result" not in rendered


def test_early_close_becomes_final_at_official_1300_et_close() -> None:
    # Friday after Thanksgiving 2026 closes at 1:00 p.m. ET.
    before_close = datetime(2026, 11, 27, 17, 30, tzinfo=UTC)
    after_close = datetime(2026, 11, 27, 18, 30, tzinfo=UTC)

    provisional = summarize(_state(), now=before_close)
    final = summarize(_state(), now=after_close)

    assert provisional["session_phase"] == "REGULAR_SESSION"
    assert provisional["zero_trade_status"] == "PROVISIONAL_SESSION_IN_PROGRESS"
    assert final["session_phase"] == "POST_SESSION"
    assert final["session_complete"] is True
    assert final["zero_trade_status"] == "FINAL_AT_AWS_BOUNDARY"
    assert final["market_session_calendar"]["scheduled_close_et"] == "13:00"
    assert final["market_session_calendar"]["early_close"] is True
    assert final["market_session_calendar"]["closure_reason"] == (
        "DAY_AFTER_THANKSGIVING"
    )


def test_christmas_eve_2026_is_official_early_close() -> None:
    schedule = core_session_for(datetime(2026, 12, 24, 18, 1, tzinfo=UTC))

    assert schedule.calendar_status == "VERIFIED"
    assert schedule.is_trading_day is True
    assert schedule.early_close is True
    assert schedule.scheduled_close_et == "13:00"
    assert schedule.session_phase == "POST_SESSION"
    assert schedule.closure_reason == "CHRISTMAS_EVE"


def test_2028_july_3_early_close_is_covered() -> None:
    schedule = core_session_for(datetime(2028, 7, 3, 18, 0, tzinfo=UTC))

    assert schedule.calendar_status == "VERIFIED"
    assert schedule.early_close is True
    assert schedule.scheduled_close_et == "13:00"
    assert schedule.session_phase == "POST_SESSION"


def test_outside_published_calendar_coverage_fails_closed() -> None:
    summary = summarize(
        _state(),
        now=datetime(2029, 1, 2, 18, 0, tzinfo=UTC),
    )

    assert summary["ok"] is False
    assert summary["session_phase"] == "CALENDAR_UNVERIFIED"
    assert summary["diagnosis"] == "SAFETY_OR_EVIDENCE_VIOLATION"
    assert "MARKET_SESSION_CALENDAR_COVERAGE_UNAVAILABLE" in summary["safety"][
        "violations"
    ]
    assert summary["market_session_calendar"]["calendar_status"] == (
        "COVERAGE_UNAVAILABLE"
    )
