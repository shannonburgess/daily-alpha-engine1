from datetime import UTC, datetime

import pytest

from daily_alpha.staging_snapshot import (
    SCHEMA_VERSION,
    build_ovtlyr_snapshot,
    load_ovtlyr_snapshot,
    write_ovtlyr_snapshot,
)


def _csv(tmp_path):
    path = tmp_path / "daily.csv"
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Vol.\n"
        "aapl,Buy,2026-08-15,Technology,Up,Accelerating,Yes,220.00,50000000\n"
        "rdw,Hold,2026-08-10,Industrials,Up,Rising,Yes,15.25,4000000\n",
        encoding="utf-8",
    )
    return path


def test_build_snapshot_normalizes_and_indexes_symbols(tmp_path):
    source = _csv(tmp_path)
    observed = datetime(2026, 8, 16, 6, 30, tzinfo=UTC)

    snapshot = build_ovtlyr_snapshot(source, observed_at=observed)

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["record_count"] == 2
    assert snapshot["buy_count"] == 1
    assert snapshot["buy_symbols"] == ["AAPL"]
    assert snapshot["symbols"]["AAPL"]["signal"] == "BUY"
    assert snapshot["symbols"]["AAPL"]["optionable"] is True
    assert snapshot["symbols"]["AAPL"]["price"] == 220.0
    assert len(snapshot["sha256"]) == 64


def test_written_snapshot_round_trips(tmp_path):
    source = _csv(tmp_path)
    destination = tmp_path / "snapshot.json"
    observed = datetime(2026, 8, 16, 6, 30, tzinfo=UTC)

    expected = write_ovtlyr_snapshot(source, destination, observed_at=observed)
    loaded = load_ovtlyr_snapshot(destination.read_text(encoding="utf-8"))

    assert loaded == expected


def test_snapshot_requires_timezone_aware_observation(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        build_ovtlyr_snapshot(
            _csv(tmp_path),
            observed_at=datetime(2026, 8, 16, 6, 30),
        )


def test_snapshot_rejects_record_count_mismatch(tmp_path):
    snapshot = build_ovtlyr_snapshot(
        _csv(tmp_path),
        observed_at=datetime(2026, 8, 16, 6, 30, tzinfo=UTC),
    )
    snapshot["record_count"] = 99

    with pytest.raises(ValueError, match="record count mismatch"):
        load_ovtlyr_snapshot(snapshot)
