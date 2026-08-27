import json
from datetime import UTC, datetime

import pytest

from daily_alpha.ovtlyr import OvtlyrRecord, compare_universes, summarize_sector_rotation
from daily_alpha.ovtlyr_report import ArchiveExistsError, archive_daily_run


def test_daily_archive_is_dated_hashed_and_immutable(tmp_path):
    source = tmp_path / "ovtlyr-export.csv"
    source.write_text("Ticker,Status\nAAA,Buy\n", encoding="utf-8")
    classified = compare_universes(
        [],
        [OvtlyrRecord(symbol="AAA", signal="BUY", optionable=True)],
    )
    sectors = summarize_sector_rotation(classified)
    history = tmp_path / "history"

    result = archive_daily_run(
        history_root=history,
        run_date="2026-08-15",
        source_csv=source,
        classified=classified,
        sectors=sectors,
        engine_version="0.1.0",
        created_at=datetime(2026, 8, 15, 17, 0, tzinfo=UTC),
    )

    assert result.run_directory == history / "2026-08-15"
    assert (result.run_directory / "universe.csv").read_text() == source.read_text()
    assert (result.run_directory / "comparison.csv").exists()
    assert (result.run_directory / "comparison.json").exists()
    assert (result.run_directory / "sector_rotation.json").exists()

    manifest = json.loads(
        (result.run_directory / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["run_date"] == "2026-08-15"
    assert manifest["source"]["sha256"] == result.source_hash_sha256
    assert manifest["optionability"]["optionable"] == 1

    latest = json.loads((history / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_date"] == "2026-08-15"

    with pytest.raises(ArchiveExistsError):
        archive_daily_run(
            history_root=history,
            run_date="2026-08-15",
            source_csv=source,
            classified=classified,
            sectors=sectors,
            engine_version="0.1.0",
        )


def test_archive_rejects_non_iso_date(tmp_path):
    source = tmp_path / "current.csv"
    source.write_text("Ticker,Status\nAAA,Buy\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        archive_daily_run(
            history_root=tmp_path / "history",
            run_date="08/15/2026",
            source_csv=source,
            classified=[],
            sectors=[],
            engine_version="0.1.0",
        )


def test_archive_rejects_latest_pointer_rewind(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "latest.json").write_text(
        json.dumps({"run_date": "2026-08-16"}), encoding="utf-8"
    )
    source = tmp_path / "current.csv"
    source.write_text("Ticker,Status\nAAA,Buy\n", encoding="utf-8")

    with pytest.raises(ArchiveExistsError, match="would not advance"):
        archive_daily_run(
            history_root=history,
            run_date="2026-08-15",
            source_csv=source,
            classified=[],
            sectors=[],
            engine_version="0.1.0",
        )

    assert not (history / "2026-08-15").exists()
    assert json.loads((history / "latest.json").read_text())["run_date"] == "2026-08-16"
