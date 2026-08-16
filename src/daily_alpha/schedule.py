"""Timezone-safe schedule gates for Daily Alpha automation."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
RUN_TIMES = frozenset({(5, 30), (14, 30)})


def is_scheduled_run_time(moment: datetime) -> bool:
    """Return true only at an approved weekday Pacific run time."""
    if moment.tzinfo is None:
        raise ValueError("schedule moment must be timezone-aware")
    local = moment.astimezone(PACIFIC)
    return local.weekday() < 5 and (local.hour, local.minute) in RUN_TIMES


def scheduled_session(moment: datetime) -> str | None:
    """Return the approved session label for a scheduled UTC instant."""
    if not is_scheduled_run_time(moment):
        return None
    local = moment.astimezone(PACIFIC)
    return "MORNING" if (local.hour, local.minute) == (5, 30) else "AFTERNOON"
