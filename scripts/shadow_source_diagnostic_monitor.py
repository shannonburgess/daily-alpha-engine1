"""Retired SH24 external source-diagnostic projection.

The former bounded external-history diagnostic has been removed from Daily Alpha.
TradingView/backend transport, durable event, replay, universe, liquidity, and PAPER
receipt evidence remain the authoritative operational controls. This compatibility
module returns a non-blocking RETIRED status so the hourly shadow monitor does not
expect a publication from a subsystem that no longer exists.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceDiagnosticStatus:
    ok: bool
    status: str
    diagnosis: str
    reason: str
    target_session_date: str
    first_due_at: str
    second_due_at: str
    publication_found: bool
    publication_target_date: str | None
    published_at_utc: str | None
    publication_age_seconds: float | None
    source_data_status: str | None
    source_diagnostic_complete: bool | None
    interpretation: str | None
    requested_symbol_count: int | None
    symbols_evaluated: int | None
    expected_entry_count: int | None
    workflow_run_id: int | None
    workflow_head_sha: str | None
    checked_at: str
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False
    tradingview_configuration_frozen: bool = True
    tradingview_mutation_attempted: bool = False


def evaluate_source_diagnostic(
    publication: dict[str, Any] | None,
    *,
    now: datetime,
) -> SourceDiagnosticStatus:
    """Return the permanent non-blocking status for the retired subsystem."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    checked = now.astimezone(UTC)
    return SourceDiagnosticStatus(
        ok=True,
        status="RETIRED",
        diagnosis="SH24_EXTERNAL_SOURCE_DIAGNOSTIC_RETIRED",
        reason=(
            "External derivatives/history-source diagnostics are no longer part of "
            "Daily Alpha. Durable TradingView/backend evidence remains authoritative."
        ),
        target_session_date="NOT_APPLICABLE",
        first_due_at="NOT_APPLICABLE",
        second_due_at="NOT_APPLICABLE",
        publication_found=False,
        publication_target_date=None,
        published_at_utc=None,
        publication_age_seconds=None,
        source_data_status="RETIRED",
        source_diagnostic_complete=None,
        interpretation="RETIRED_NON_BLOCKING_CONTROL",
        requested_symbol_count=None,
        symbols_evaluated=None,
        expected_entry_count=None,
        workflow_run_id=None,
        workflow_head_sha=None,
        checked_at=checked.isoformat(),
    )


def render_markdown(status: SourceDiagnosticStatus) -> str:
    return "\n".join(
        [
            "",
            "### SH24 external source diagnostic",
            f"Status: **{status.status}**  ",
            f"Diagnosis: `{status.diagnosis}`  ",
            f"Reason: {status.reason}  ",
            "TradingView configuration: **frozen; private alert membership is not inferred**  ",
            (
                "Safety: `research_only=true`, `promotion_authorized=false`, "
                "`trading_authorized=false`, `live_trading_enabled=false`"
            ),
            "",
        ]
    )


def _load(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    status = evaluate_source_diagnostic(_load(args.publication), now=datetime.now(UTC))
    Path(args.output_json).write_text(
        json.dumps(asdict(status), indent=2, sort_keys=True) + "\n"
    )
    Path(args.output_md).write_text(render_markdown(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
