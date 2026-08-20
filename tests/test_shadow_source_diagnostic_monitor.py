from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.shadow_source_diagnostic_monitor import (
    evaluate_source_diagnostic,
    render_markdown,
)


def _publication(
    *,
    target_date: str = "2026-08-20",
    published_at: str = "2026-08-21T03:40:00+00:00",
    source_data_status: str = "COMPLETE",
    complete: bool = True,
) -> dict:
    return {
        "schema_version": "SH24_SOURCE_DIAGNOSTIC_PUBLICATION_V1",
        "workflow": "diagnose-shadow-signal-coverage.yml",
        "run_id": 12345,
        "head_sha": "a" * 40,
        "event": "schedule",
        "published_at_utc": published_at,
        "target_date": target_date,
        "source_data_status": source_data_status,
        "source_diagnostic_complete": complete,
        "interpretation": "SH24_SOURCE_EXPECTATIONS_RECONCILED",
        "requested_symbol_count": 214,
        "symbols_evaluated": 214,
        "expected_entry_count": 7,
        "diagnostic_sha256": "b" * 64,
        "research_only": True,
        "promotion_authorized": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def test_current_completed_publication_passes() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    status = evaluate_source_diagnostic(_publication(), now=now)

    assert status.ok is True
    assert status.status == "PASS"
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_COMPLETE"
    assert status.target_session_date == "2026-08-20"
    assert status.expected_entry_count == 7
    assert status.trading_authorized is False
    assert status.live_trading_enabled is False
    assert "private alert membership is not inferred" in render_markdown(status)


def test_uniform_provider_publication_delay_is_pending_not_false_zero() -> None:
    now = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    publication = _publication(
        published_at="2026-08-21T06:40:00+00:00",
        source_data_status="PENDING_PROVIDER_PUBLICATION",
        complete=False,
    )

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.ok is True
    assert status.status == "PENDING"
    assert status.diagnosis == "SH24_SOURCE_DATA_PENDING_PROVIDER_PUBLICATION"
    assert "no zero-signal inference" in status.reason


def test_partial_or_other_incomplete_evidence_fails_closed() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    publication = _publication(source_data_status="PARTIAL_PROVIDER_PUBLICATION", complete=False)

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.ok is False
    assert status.status == "FAIL"
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_INCOMPLETE"


def test_prior_session_publication_is_pending_before_first_attempt_grace() -> None:
    now = datetime(2026, 8, 21, 3, 30, tzinfo=UTC)
    publication = _publication(
        target_date="2026-08-19",
        published_at="2026-08-20T06:40:00+00:00",
    )

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.ok is True
    assert status.status == "PENDING"
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_CURRENT_SESSION_NOT_DUE"


def test_prior_session_publication_fails_after_first_attempt_grace() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    publication = _publication(
        target_date="2026-08-19",
        published_at="2026-08-20T06:40:00+00:00",
    )

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.ok is False
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_STALE_TARGET"


def test_missing_publication_is_pending_before_first_attempt_grace() -> None:
    now = datetime(2026, 8, 21, 3, 30, tzinfo=UTC)
    status = evaluate_source_diagnostic(None, now=now)

    assert status.ok is True
    assert status.status == "PENDING"
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_NOT_DUE"


def test_missing_publication_fails_after_first_attempt_grace() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    status = evaluate_source_diagnostic(None, now=now)

    assert status.ok is False
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_PUBLICATION_MISSING"


def test_future_target_fails_closed() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    status = evaluate_source_diagnostic(_publication(target_date="2026-08-21"), now=now)

    assert status.ok is False
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_FUTURE_TARGET"


def test_safety_contract_violation_fails_closed() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    publication = _publication()
    publication["trading_authorized"] = True

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.ok is False
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_PUBLICATION_INVALID"
    assert "trading_authorized" in status.reason


def test_future_publication_timestamp_fails_closed() -> None:
    now = datetime(2026, 8, 21, 4, 50, tzinfo=UTC)
    publication = _publication(published_at="2026-08-21T05:00:00+00:00")

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.ok is False
    assert status.diagnosis == "SH24_SOURCE_DIAGNOSTIC_PUBLICATION_INVALID"
    assert "future" in status.reason


def test_non_trading_day_uses_latest_completed_verified_session() -> None:
    now = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)  # Labor Day
    publication = _publication(
        target_date="2026-09-04",
        published_at="2026-09-05T03:40:00+00:00",
    )

    status = evaluate_source_diagnostic(publication, now=now)

    assert status.target_session_date == "2026-09-04"
    assert status.ok is True


def test_naive_now_is_rejected() -> None:
    naive = datetime(2026, 8, 21, 4, 50, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_source_diagnostic(_publication(), now=naive)


def test_direct_cli_invocation_emits_safety_bounded_result(tmp_path: Path) -> None:
    publication_path = tmp_path / "publication.json"
    output_json = tmp_path / "status.json"
    output_md = tmp_path / "status.md"
    publication_path.write_text(json.dumps(_publication(target_date="2026-08-19")) + "\n")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/shadow_source_diagnostic_monitor.py",
            "--publication",
            str(publication_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode in {0, 2}, completed.stderr
    payload = json.loads(output_json.read_text())
    assert payload["research_only"] is True
    assert payload["promotion_authorized"] is False
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False
    assert "SH24 source-side diagnostic health" in output_md.read_text()
