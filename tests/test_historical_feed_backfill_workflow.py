# ruff: noqa: I001

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import staging_lambda_handlers.data_feed_ingest as ingest


WORKFLOW = Path(".github/workflows/capture-historical-staging-data-feeds.yml")


def test_provider_free_smoke_contract_requires_no_secret_or_bucket(monkeypatch):
    def _secret_must_not_be_loaded(provider):
        raise AssertionError(f"smoke test must not load provider secret: {provider}")

    monkeypatch.delenv("RAW_EVIDENCE_BUCKET", raising=False)
    monkeypatch.setattr(ingest, "_load_secret", _secret_must_not_be_loaded)

    result = ingest.lambda_handler(
        {"smoke_test": True},
        SimpleNamespace(aws_request_id="smoke"),
    )

    assert result["ok"] is True
    assert result["historical_backfill_supported"] is True
    assert result["capture_modes"] == ["CURRENT_WINDOW", "HISTORICAL_BACKFILL"]
    assert result["max_historical_backfill_days"] == 31
    assert result["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert result["historical_known_at_backdating_authorized"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_historical_capture_workflow_is_manual_only_and_main_locked():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "push:" not in text
    assert 'test "$GITHUB_REF_NAME" = "main"' in text
    assert 'git rev-parse origin/main' in text
    assert "environment: staging" in text
    assert "daily-alpha-staging-data-feed-ingestion" in text


def test_workflow_requires_explicit_capture_confirmation_and_bounded_dates():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Type CAPTURE" in text
    assert "BACKFILL_CONFIRMATION_REQUIRED" in text
    assert "BACKFILL_DATE_RANGE_TOO_LARGE" in text
    assert "BACKFILL_END_DATE_IN_FUTURE" in text
    assert "31" in text
    assert "HISTORICAL_BACKFILL" in text


def test_workflow_smokes_capability_before_any_historical_provider_call():
    text = WORKFLOW.read_text(encoding="utf-8")

    smoke_name = "Require deployed backfill-aware ingestion contract before provider call"
    capture_name = "Capture requested historical evidence"
    assert smoke_name in text
    assert capture_name in text
    assert text.index(smoke_name) < text.index(capture_name)
    assert '{\"smoke_test\":true}' in text
    assert "historical_backfill_supported" in text
    assert "max_historical_backfill_days" in text


def test_workflow_never_claims_historical_known_at_or_execution_authority():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "CAPTURED_AT_ONLY" in text
    assert "historical_known_at_backdating_authorized" in text
    assert "historical_known_at_backdating_authorized': False" in text
    assert "trading_authorized': False" in text
    assert "live_trading_enabled': False" in text
    assert "does **not** authorize historical `known_at` backdating" in text
