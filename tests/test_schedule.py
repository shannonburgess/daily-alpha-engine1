from datetime import UTC, datetime

import pytest

from daily_alpha.schedule import is_scheduled_run_time, scheduled_session


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 1, 5, 13, 30, tzinfo=UTC),
        datetime(2026, 1, 5, 22, 30, tzinfo=UTC),
        datetime(2026, 8, 17, 12, 30, tzinfo=UTC),
        datetime(2026, 8, 17, 21, 30, tzinfo=UTC),
    ],
)
def test_schedule_handles_standard_and_daylight_time(moment):
    assert is_scheduled_run_time(moment) is True


def test_wrong_utc_offset_and_weekend_are_rejected():
    assert is_scheduled_run_time(datetime(2026, 8, 17, 13, 30, tzinfo=UTC)) is False
    assert is_scheduled_run_time(datetime(2026, 8, 16, 12, 30, tzinfo=UTC)) is False


def test_schedule_labels_morning_and_afternoon_runs():
    assert scheduled_session(datetime(2026, 8, 17, 12, 30, tzinfo=UTC)) == "MORNING"
    assert scheduled_session(datetime(2026, 8, 17, 21, 30, tzinfo=UTC)) == "AFTERNOON"
    assert scheduled_session(datetime(2026, 8, 17, 20, 30, tzinfo=UTC)) is None


def test_naive_schedule_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        is_scheduled_run_time(datetime(2026, 8, 17, 12, 30))  # noqa: DTZ001
