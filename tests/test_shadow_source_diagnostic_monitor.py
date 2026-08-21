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


def test_retired_source_diagnostic_is_non_blocking() -> None:
    now = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
    status = evaluate_source_diagnostic(None, now=now)

    assert status.ok is True
    assert status.status == "RETIRED"
    assert status.diagnosis == "SH24_EXTERNAL_SOURCE_DIAGNOSTIC_RETIRED"
    assert status.source_data_status == "RETIRED"
    assert status.trading_authorized is False
    assert status.live_trading_enabled is False
    assert "Durable TradingView/backend evidence" in status.reason


def test_old_publication_is_ignored_after_retirement() -> None:
    now = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
    status = evaluate_source_diagnostic(
        {"legacy": "publication", "trading_authorized": True},
        now=now,
    )

    assert status.ok is True
    assert status.publication_found is False
    assert status.interpretation == "RETIRED_NON_BLOCKING_CONTROL"


def test_naive_now_is_rejected() -> None:
    naive = datetime(2026, 8, 21, 20, 0, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_source_diagnostic(None, now=naive)


def test_markdown_states_retired_safety_boundary() -> None:
    status = evaluate_source_diagnostic(None, now=datetime(2026, 8, 21, 20, 0, tzinfo=UTC))
    text = render_markdown(status)

    assert "SH24 external source diagnostic" in text
    assert "RETIRED" in text
    assert "trading_authorized=false" in text
    assert "live_trading_enabled=false" in text


def test_direct_cli_invocation_emits_retired_result(tmp_path: Path) -> None:
    output_json = tmp_path / "status.json"
    output_md = tmp_path / "status.md"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/shadow_source_diagnostic_monitor.py",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output_json.read_text())
    assert payload["status"] == "RETIRED"
    assert payload["research_only"] is True
    assert payload["promotion_authorized"] is False
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False
    assert "SH24 external source diagnostic" in output_md.read_text()
