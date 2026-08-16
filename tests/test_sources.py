import os
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.orats import OratsDataError, OratsNoOptionsError
from daily_alpha.sources import OratsBatchSource, OvtlyrInbox, SourceError

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


class FakeClient:
    def fetch_chain(self, symbol, *, as_of):
        if symbol == "NOOPT":
            raise OratsNoOptionsError("no rows")
        if symbol == "BAD":
            raise OratsDataError("sensitive upstream detail")
        return (symbol, as_of)


def test_orats_batch_deduplicates_symbols_and_returns_safe_error_codes():
    result = OratsBatchSource(FakeClient()).fetch(
        ("aapl", "AAPL", "NOOPT", "BAD"), as_of=NOW
    )
    assert len(result.chains) == 1
    assert result.errors == (
        ("NOOPT", "ORATS_NO_45_75_DTE_OPTIONS"),
        ("BAD", "ORATS_DATA_ERROR"),
    )
    assert result.complete is False
    assert "sensitive" not in repr(result)


def test_empty_orats_batch_is_complete():
    result = OratsBatchSource(FakeClient()).fetch((), as_of=NOW)
    assert result.complete is True
