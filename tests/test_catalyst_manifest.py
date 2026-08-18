from datetime import date, datetime, timezone

import pytest

from daily_alpha.catalyst_manifest import (
    CatalystManifestRecord,
    record_from_dict,
    validate_manifest_record,
)
from daily_alpha.pre_catalyst import CatalystType


def valid_record() -> CatalystManifestRecord:
    return CatalystManifestRecord(
        ticker="NVDA",
        event_type=CatalystType.PRODUCT_LAUNCH,
        event_date=date(2026, 9, 10),
        event_known_at=datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc),
        source_url="https://investor.nvidia.com/example-event",
        source_first_seen_at=datetime(2026, 8, 1, 16, 5, tzinfo=timezone.utc),
        source_sha256="a" * 64,
        source_title="Example public event",
    )


def test_manifest_produces_deterministic_public_catalyst() -> None:
    record = valid_record()
    validate_manifest_record(record)
    first = record.as_public_catalyst()
    second = record.as_public_catalyst()
    assert first.source_id == second.source_id == record.event_id
    assert first.ticker == "NVDA"
    assert first.event_known_date == date(2026, 8, 1)


def test_manifest_id_changes_when_source_evidence_changes() -> None:
    record = valid_record()
    changed = CatalystManifestRecord(
        **{**record.__dict__, "source_sha256": "b" * 64}
    )
    assert record.event_id != changed.event_id


def test_manifest_rejects_source_seen_before_public_known_time() -> None:
    record = valid_record()
    invalid = CatalystManifestRecord(
        **{
            **record.__dict__,
            "source_first_seen_at": datetime(2026, 8, 1, 15, 59, tzinfo=timezone.utc),
        }
    )
    with pytest.raises(ValueError, match="cannot precede"):
        validate_manifest_record(invalid)


def test_manifest_rejects_naive_timestamps() -> None:
    record = valid_record()
    invalid = CatalystManifestRecord(
        **{**record.__dict__, "event_known_at": datetime(2026, 8, 1, 16, 0)}
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_manifest_record(invalid)


def test_manifest_rejects_non_https_source() -> None:
    record = valid_record()
    invalid = CatalystManifestRecord(
        **{**record.__dict__, "source_url": "http://example.com/event"}
    )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_manifest_record(invalid)


def test_record_from_dict_requires_complete_point_in_time_evidence() -> None:
    payload = {
        "ticker": "NVDA",
        "event_type": "PRODUCT_LAUNCH",
        "event_date": "2026-09-10",
        "event_known_at": "2026-08-01T16:00:00Z",
        "source_url": "https://investor.nvidia.com/example-event",
        "source_first_seen_at": "2026-08-01T16:05:00Z",
        "source_sha256": "c" * 64,
    }
    record = record_from_dict(payload)
    assert record.ticker == "NVDA"
    assert record.event_known_at.utcoffset() is not None


def test_record_from_dict_fails_closed_when_source_hash_missing() -> None:
    payload = {
        "ticker": "NVDA",
        "event_type": "PRODUCT_LAUNCH",
        "event_date": "2026-09-10",
        "event_known_at": "2026-08-01T16:00:00Z",
        "source_url": "https://investor.nvidia.com/example-event",
        "source_first_seen_at": "2026-08-01T16:05:00Z",
        "source_sha256": "",
    }
    with pytest.raises(ValueError, match="source_sha256"):
        record_from_dict(payload)
