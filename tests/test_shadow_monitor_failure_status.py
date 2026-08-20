from datetime import UTC, datetime

import pytest

from scripts.shadow_monitor_failure_status import build_failure_status, render_markdown


def test_failure_status_never_reuses_prior_green_state() -> None:
    status = build_failure_status(
        now=datetime(2026, 8, 20, 10, 30, tzinfo=UTC),
        repository="shannonburgess/daily-alpha-engine1",
        workflow="Monitor Daily Alpha paper shadows",
        run_id="123",
        run_attempt="2",
        head_sha="abc123",
        failed_step="Read isolated positions, ARMED state, events and receipts",
    )

    assert status["ok"] is False
    assert status["diagnosis"] == "MONITOR_PIPELINE_FAILURE"
    assert status["current_shadow_state_verified"] is False
    assert status["prior_state_reused"] is False
    assert status["runtime_safety_state"] == "UNVERIFIED_CURRENT_RUN"
    assert status["tradingview_configuration_frozen"] is True
    assert status["tradingview_mutation_attempted"] is False
    assert status["failed_step"] == "Read isolated positions, ARMED state, events and receipts"

    markdown = render_markdown(status)
    assert markdown.startswith("<!-- daily-alpha-shadow-monitor -->")
    assert "MONITOR_PIPELINE_FAILURE" in markdown
    assert "Do **not** interpret the prior issue status" in markdown
    assert "Read isolated positions, ARMED state, events and receipts" in markdown
    assert "`123` / `2`" in markdown
    assert "`abc123`" in markdown


def test_failure_status_requires_timezone_aware_time() -> None:
    naive_time = datetime(2026, 8, 20, 10, 30, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_failure_status(
            now=naive_time,
            repository="shannonburgess/daily-alpha-engine1",
            workflow="Monitor Daily Alpha paper shadows",
            run_id="123",
            run_attempt="1",
            head_sha="abc123",
        )
