"""Emit a fail-closed status when the PAPER-shadow monitor cannot complete.

This is deliberately separate from the normal shadow diagnosis. It prevents a stale
prior green issue comment from looking current when the workflow fails before the
read-only staging snapshot can be summarized.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def build_failure_status(
    *,
    now: datetime,
    repository: str,
    workflow: str,
    run_id: str,
    run_attempt: str,
    head_sha: str,
) -> dict[str, object]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    return {
        "ok": False,
        "snapshot_at": now.astimezone(UTC).isoformat(),
        "diagnosis": "MONITOR_PIPELINE_FAILURE",
        "current_shadow_state_verified": False,
        "prior_state_reused": False,
        "tradingview_configuration_frozen": True,
        "tradingview_mutation_attempted": False,
        "runtime_safety_state": "UNVERIFIED_CURRENT_RUN",
        "repository": repository,
        "workflow": workflow,
        "run_id": str(run_id),
        "run_attempt": str(run_attempt),
        "head_sha": head_sha,
        "reason": (
            "The monitor workflow failed before a complete current read-only staging "
            "snapshot could be summarized. Prior green evidence is not reused as a "
            "current zero-trade diagnosis."
        ),
    }


def render_markdown(status: dict[str, object]) -> str:
    return "\n".join(
        [
            "<!-- daily-alpha-shadow-monitor -->",
            "## Daily Alpha PAPER Shadow Monitor",
            "",
            "**Diagnosis:** `MONITOR_PIPELINE_FAILURE`  ",
            "**Current PAPER-shadow state verified:** False  ",
            "**Prior green state reused:** False  ",
            "**Current runtime safety state:** `UNVERIFIED_CURRENT_RUN`  ",
            "**TradingView configuration:** frozen; no mutation attempted",
            "",
            "The monitor workflow failed before it could produce a complete current "
            "read-only staging snapshot. Do **not** interpret the prior issue status as "
            "a current zero-trade, position, ARMED, receipt, or safety diagnosis.",
            "",
            "### Monitor run evidence",
            f"Repository: `{status['repository']}`  ",
            f"Workflow: `{status['workflow']}`  ",
            f"Run ID / attempt: `{status['run_id']}` / `{status['run_attempt']}`  ",
            f"Head SHA: `{status['head_sha']}`  ",
            f"Failure receipt generated at: `{status['snapshot_at']}`",
            "",
        ]
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    status = build_failure_status(
        now=datetime.now(UTC),
        repository=args.repository,
        workflow=args.workflow,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        head_sha=args.head_sha,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    args.output_md.write_text(render_markdown(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
