import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from daily_alpha.ovtlyr_ingestion import (
    OvtlyrIngestionError,
    ingest_ovtlyr_export,
    ingest_transform_archive,
    transform_ovtlyr_exports,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _copy_export(tmp_path: Path, source_date: str) -> Path:
    destination = tmp_path / f"OVTLYR_{source_date}.csv"
    shutil.copyfile(
        REPOSITORY_ROOT / "data" / "history" / source_date / "universe.csv",
        destination,
    )
    return destination


def _rewrite(path: Path, mutate) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    mutate(fieldnames, rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_ingests_real_22_column_export_without_collapsing_partial_rows(tmp_path):
    export = ingest_ovtlyr_export(_copy_export(tmp_path, "2026-08-25"))

    assert export.header_count == 22
    assert export.row_count == 1230
    assert export.partial_row_count == 108
    assert len(export.records) == 1230
    assert sum(record.signal == "BUY" for record in export.records) == 366
    assert sum(record.signal == "" for record in export.records) == 108


def test_transform_reproduces_388_matched_symbol_transition_counts(tmp_path):
    previous = _copy_export(tmp_path, "2026-08-24")
    current = _copy_export(tmp_path, "2026-08-25")

    result = transform_ovtlyr_exports(previous, current)
    counts: dict[str, int] = {}
    for item in result.classified:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1

    assert len(result.classified) == 1238
    assert counts == {
        "ACTIVE_BUY": 17,
        "DETERIORATING": 44,
        "EMERGING": 33,
        "LEADER": 271,
        "NEW_BUY": 1,
        "REMOVED": 44,
        "UNCHANGED": 828,
    }
    assert len(result.sectors) == 11
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_archive_manifest_carries_validation_lineage_and_safety_flags(tmp_path):
    previous = _copy_export(tmp_path, "2026-08-24")
    current = _copy_export(tmp_path, "2026-08-25")

    _, archive = ingest_transform_archive(
        previous_csv=previous,
        current_csv=current,
        history_root=tmp_path / "history",
        engine_version="test",
        run_date="2026-08-25",
        created_at=datetime(2026, 8, 25, 22, 0, tzinfo=UTC),
    )
    manifest = json.loads(
        (archive.run_directory / "run_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["baseline"]["source_date"] == "2026-08-24"
    assert manifest["validation"] == {
        "contract": "OVTLYR_22_COLUMN_SWING_V1",
        "header_count": 22,
        "source_row_count": 1230,
        "partial_row_count": 108,
        "rejected_row_count": 0,
        "transition_method": "MATCHED_SYMBOL_DAY_OVER_DAY",
    }
    assert manifest["trading_authorized"] is False
    assert manifest["live_trading_enabled"] is False


def test_rejects_bad_numeric_instead_of_converting_it_to_zero(tmp_path):
    current = _copy_export(tmp_path, "2026-08-25")
    _rewrite(
        current,
        lambda _fieldnames, rows: rows[0].__setitem__(
            "Last Close Price ($)", "not-a-price"
        ),
    )

    with pytest.raises(OvtlyrIngestionError, match="OVTLYR_PRICE_INVALID:2"):
        ingest_ovtlyr_export(current)


def test_rejects_duplicate_symbols_and_normalized_headers(tmp_path):
    current = _copy_export(tmp_path, "2026-08-25")
    _rewrite(current, lambda _fieldnames, rows: rows.append(dict(rows[0])))
    with pytest.raises(OvtlyrIngestionError, match="OVTLYR_DUPLICATE_SYMBOL"):
        ingest_ovtlyr_export(current)

    current = _copy_export(tmp_path, "2026-08-25")
    text = current.read_text(encoding="utf-8")
    current.write_text(text.replace("Company Name", "Symbol", 1), encoding="utf-8")
    with pytest.raises(OvtlyrIngestionError, match="OVTLYR_DUPLICATE_HEADER"):
        ingest_ovtlyr_export(current)


def test_rejects_future_signal_date_and_filename_date_mismatch(tmp_path):
    current = _copy_export(tmp_path, "2026-08-25")
    _rewrite(
        current,
        lambda _fieldnames, rows: rows[0].__setitem__(
            "Signal Start Date", "Aug 26, 2026"
        ),
    )
    with pytest.raises(OvtlyrIngestionError, match="SIGNAL_DATE_IN_FUTURE"):
        ingest_ovtlyr_export(current)

    previous = _copy_export(tmp_path, "2026-08-24")
    current = _copy_export(tmp_path, "2026-08-25")
    with pytest.raises(OvtlyrIngestionError, match="RUN_DATE_SOURCE_DATE_MISMATCH"):
        ingest_transform_archive(
            previous_csv=previous,
            current_csv=current,
            history_root=tmp_path / "history",
            engine_version="test",
            run_date="2026-08-26",
        )


def test_rejects_nonadvancing_baseline_and_bad_filename(tmp_path):
    current = _copy_export(tmp_path, "2026-08-25")
    with pytest.raises(OvtlyrIngestionError, match="BASELINE_NOT_BEFORE_CURRENT"):
        transform_ovtlyr_exports(current, current)

    bad_name = tmp_path / "latest.csv"
    shutil.copyfile(current, bad_name)
    with pytest.raises(OvtlyrIngestionError, match="OVTLYR_FILENAME_INVALID"):
        ingest_ovtlyr_export(bad_name)
