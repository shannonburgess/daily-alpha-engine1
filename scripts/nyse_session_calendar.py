"""Versioned NYSE core-session calendar for exact PAPER-shadow session diagnosis.

The dates below are transcribed from the NYSE Holidays & Trading Hours page for
2026-2028. Coverage is deliberately bounded: dates outside the published range fail
closed rather than being guessed from weekday/federal-holiday heuristics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
CALENDAR_VERSION = "NYSE_CORE_2026_2028_V1"
CALENDAR_SOURCE_URL = "https://www.nyse.com/trade/hours-calendars"
COVERED_YEARS = frozenset({2026, 2027, 2028})
CORE_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

FULL_DAY_CLOSURES: dict[date, str] = {
    # 2026
    date(2026, 1, 1): "NEW_YEARS_DAY",
    date(2026, 1, 19): "MARTIN_LUTHER_KING_JR_DAY",
    date(2026, 2, 16): "WASHINGTONS_BIRTHDAY",
    date(2026, 4, 3): "GOOD_FRIDAY",
    date(2026, 5, 25): "MEMORIAL_DAY",
    date(2026, 6, 19): "JUNETEENTH",
    date(2026, 7, 3): "INDEPENDENCE_DAY_OBSERVED",
    date(2026, 9, 7): "LABOR_DAY",
    date(2026, 11, 26): "THANKSGIVING_DAY",
    date(2026, 12, 25): "CHRISTMAS_DAY",
    # 2027
    date(2027, 1, 1): "NEW_YEARS_DAY",
    date(2027, 1, 18): "MARTIN_LUTHER_KING_JR_DAY",
    date(2027, 2, 15): "WASHINGTONS_BIRTHDAY",
    date(2027, 3, 26): "GOOD_FRIDAY",
    date(2027, 5, 31): "MEMORIAL_DAY",
    date(2027, 6, 18): "JUNETEENTH_OBSERVED",
    date(2027, 7, 5): "INDEPENDENCE_DAY_OBSERVED",
    date(2027, 9, 6): "LABOR_DAY",
    date(2027, 11, 25): "THANKSGIVING_DAY",
    date(2027, 12, 24): "CHRISTMAS_DAY_OBSERVED",
    # 2028 — NYSE notes no New Year's Day closure because Jan 1 falls Saturday.
    date(2028, 1, 17): "MARTIN_LUTHER_KING_JR_DAY",
    date(2028, 2, 21): "WASHINGTONS_BIRTHDAY",
    date(2028, 4, 14): "GOOD_FRIDAY",
    date(2028, 5, 29): "MEMORIAL_DAY",
    date(2028, 6, 19): "JUNETEENTH",
    date(2028, 7, 4): "INDEPENDENCE_DAY",
    date(2028, 9, 4): "LABOR_DAY",
    date(2028, 11, 23): "THANKSGIVING_DAY",
    date(2028, 12, 25): "CHRISTMAS_DAY",
}

EARLY_CLOSES: dict[date, str] = {
    date(2026, 11, 27): "DAY_AFTER_THANKSGIVING",
    date(2026, 12, 24): "CHRISTMAS_EVE",
    date(2027, 11, 26): "DAY_AFTER_THANKSGIVING",
    date(2028, 7, 3): "DAY_BEFORE_INDEPENDENCE_DAY",
    date(2028, 11, 24): "DAY_AFTER_THANKSGIVING",
}


@dataclass(frozen=True)
class NyseCoreSession:
    calendar_version: str
    calendar_source_url: str
    calendar_status: str
    session_date_et: str
    is_trading_day: bool | None
    session_phase: str
    scheduled_open_et: str | None
    scheduled_close_et: str | None
    early_close: bool
    closure_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def core_session_for(timestamp: datetime) -> NyseCoreSession:
    """Return the official scheduled NYSE core-session state at ``timestamp``."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")

    local = timestamp.astimezone(NEW_YORK)
    session_date = local.date()
    if session_date.year not in COVERED_YEARS:
        return NyseCoreSession(
            calendar_version=CALENDAR_VERSION,
            calendar_source_url=CALENDAR_SOURCE_URL,
            calendar_status="COVERAGE_UNAVAILABLE",
            session_date_et=session_date.isoformat(),
            is_trading_day=None,
            session_phase="CALENDAR_UNVERIFIED",
            scheduled_open_et=None,
            scheduled_close_et=None,
            early_close=False,
            closure_reason="DATE_OUTSIDE_PUBLISHED_2026_2028_CALENDAR",
        )

    if local.weekday() >= 5:
        return _closed_session(session_date, "WEEKEND")

    closure = FULL_DAY_CLOSURES.get(session_date)
    if closure:
        return _closed_session(session_date, closure)

    early_close_reason = EARLY_CLOSES.get(session_date)
    close_time = EARLY_CLOSE if early_close_reason else REGULAR_CLOSE
    local_clock = local.time().replace(tzinfo=None)
    if local_clock < CORE_OPEN:
        phase = "PREMARKET"
    elif local_clock < close_time:
        phase = "REGULAR_SESSION"
    else:
        phase = "POST_SESSION"

    return NyseCoreSession(
        calendar_version=CALENDAR_VERSION,
        calendar_source_url=CALENDAR_SOURCE_URL,
        calendar_status="VERIFIED",
        session_date_et=session_date.isoformat(),
        is_trading_day=True,
        session_phase=phase,
        scheduled_open_et=_format_clock(CORE_OPEN),
        scheduled_close_et=_format_clock(close_time),
        early_close=early_close_reason is not None,
        closure_reason=early_close_reason,
    )


def _closed_session(session_date: date, reason: str) -> NyseCoreSession:
    return NyseCoreSession(
        calendar_version=CALENDAR_VERSION,
        calendar_source_url=CALENDAR_SOURCE_URL,
        calendar_status="VERIFIED",
        session_date_et=session_date.isoformat(),
        is_trading_day=False,
        session_phase="NON_TRADING_DAY",
        scheduled_open_et=None,
        scheduled_close_et=None,
        early_close=False,
        closure_reason=reason,
    )


def _format_clock(value: time) -> str:
    return value.strftime("%H:%M")
