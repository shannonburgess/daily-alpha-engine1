from datetime import UTC, datetime

from daily_alpha.pine_paper_orchestrator import _regular_execution_window


def test_regular_execution_window_opens_at_930_et():
    # 2026-08-18 is EDT (UTC-4).
    assert not _regular_execution_window(datetime(2026, 8, 18, 13, 29, 59, tzinfo=UTC))
    assert _regular_execution_window(datetime(2026, 8, 18, 13, 30, 0, tzinfo=UTC))
    assert _regular_execution_window(datetime(2026, 8, 18, 13, 31, 0, tzinfo=UTC))


def test_regular_execution_window_runs_through_35959_et():
    assert _regular_execution_window(datetime(2026, 8, 18, 19, 50, 0, tzinfo=UTC))
    assert _regular_execution_window(datetime(2026, 8, 18, 19, 59, 59, tzinfo=UTC))
    assert not _regular_execution_window(datetime(2026, 8, 18, 20, 0, 0, tzinfo=UTC))


def test_regular_execution_window_is_closed_on_weekends():
    assert not _regular_execution_window(datetime(2026, 8, 22, 15, 0, 0, tzinfo=UTC))
