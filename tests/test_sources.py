import os
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.sources import OvtlyrInbox, SourceError

NOW = datetime(2026, 8, 15, 13, 0, tzinfo=UTC)


def set_modified(path, value):
    timestamp = value.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_inbox_selects_newest_complete_nonempty_csv(tmp_path):
    old = tmp_path / "2026-08-14.csv"
    new = tmp_path / "2026-08-15.csv"
    partial = tmp_path / "upload.partial.csv"
    old.write_text("symbol\nAAPL\n")
    new.write_text("symbol\nMSFT\n")
    partial.write_text("symbol\nNVDA\n")
    set_modified(old, NOW - timedelta(hours=24))
    set_modified(new, NOW - timedelta(hours=1))
    set_modified(partial, NOW)
    result = OvtlyrInbox(tmp_path).latest(as_of=NOW)
    assert result.path == new
    assert result.size_bytes > 0


def test_missing_and_stale_inbox_fail_closed(tmp_path):
    with pytest.raises(SourceError, match="CSV_MISSING"):
        OvtlyrInbox(tmp_path).latest(as_of=NOW)
    old = tmp_path / "old.csv"
    old.write_text("symbol\nAAPL\n")
    set_modified(old, NOW - timedelta(hours=48))
    with pytest.raises(SourceError, match="CSV_STALE"):
        OvtlyrInbox(tmp_path).latest(as_of=NOW)


def test_inbox_rejects_naive_as_of(tmp_path):
    path = tmp_path / "today.csv"
    path.write_text("symbol\nAAPL\n")
    set_modified(path, NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        OvtlyrInbox(tmp_path).latest(as_of=NOW.replace(tzinfo=None))
