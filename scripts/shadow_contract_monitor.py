"""Fail-closed runtime/source-contract checks for Daily Alpha PAPER shadows."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SHADOW_ACCOUNTS = ("PAPER_SHADOW_V24", "PAPER_SHADOW_V25")
TEST_SIGNAL_MARKERS = ("E2E", "CONNECTIVITY", "SYSTEM-ROUNDTRIP", "STAGING-READINESS")
ENTRY_ACTIONS = {"ENTRY", "ENTRY_LONG", "ARMED_BREAKOUT_CONFIRM", "BREAKOUT_ENTRY"}
_PENDING_DEPLOY_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}


def _is_test_event(event: dict[str, Any]) -> bool:
    signal_id = str(event.get("signal_id") or "").upper()
    symbol = str(event.get("symbol") or "").upper()
    return any(marker in signal_id for marker in TEST_SIGNAL_MARKERS) or symbol == "DAE2E"


def _positive_finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def inspect_contract(
    state: dict[str, Any],
    runtime: dict[str, Any],
    deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect deployed staging and durable shadow evidence for contract drift."""
    violations: list[str] = []
    expected_start = str(runtime.get("expected_forward_test_start") or "").strip()
    deployed_start = str(runtime.get("forward_test_start") or "").strip()

    if not expected_start:
        violations.append("EXPECTED_FORWARD_TEST_START_MISSING")
    if str(runtime.get("state") or "") != "Active":
        violations.append(f"PROCESSOR_STATE_NOT_ACTIVE:{runtime.get('state')}")
    if str(runtime.get("last_update_status") or "") != "Successful":
        violations.append(
            f"PROCESSOR_LAST_UPDATE_NOT_SUCCESSFUL:{runtime.get('last_update_status')}"
        )
    if expected_start and deployed_start != expected_start:
        violations.append(
            f"PROCESSOR_FORWARD_START_DRIFT:{deployed_start or 'MISSING'}!={expected_start}"
        )

    deployment_found = None
    deployment_status = None
    deployment_conclusion = None
    deployment_head_sha = None
    deployment_run_id = None
    deployment_pending = False
    if deployment is not None:
        deployment_found = deployment.get("found") is True
        deployment_status = str(deployment.get("status") or "").strip() or None
        deployment_conclusion = str(deployment.get("conclusion") or "").strip() or None
        deployment_head_sha = str(deployment.get("head_sha") or "").strip() or None
        deployment_run_id = deployment.get("run_id")
        if not deployment_found:
            violations.append("STAGING_DEPLOYMENT_EVIDENCE_MISSING")
        elif not deployment_head_sha:
            violations.append("LATEST_STAGING_DEPLOY_HEAD_SHA_MISSING")
        elif deployment_status == "completed":
            if deployment_conclusion != "success":
                violations.append(
                    "LATEST_STAGING_DEPLOY_NOT_SUCCESSFUL:"
                    f"{deployment_conclusion or 'MISSING'}"
                )
        elif deployment_status in _PENDING_DEPLOY_STATUSES:
            deployment_pending = True
        else:
            violations.append(
                "LATEST_STAGING_DEPLOY_STATUS_INVALID:"
                f"{deployment_status or 'MISSING'}"
            )

    books = state.get("books")
    if not isinstance(books, dict):
        violations.append("MONITOR_BOOKS_MISSING")
        books = {}

    checked_strategy_events = 0
    checked_armed_signals = 0

    for account in SHADOW_ACCOUNTS:
        book = books.get(account)
        if not isinstance(book, dict):
            violations.append(f"{account}:BOOK_MISSING")
            continue

        if book.get("armed_limit_reached") is True:
            violations.append(f"{account}:ARMED_EVIDENCE_LIMIT_REACHED")

        armed = book.get("armed_signals", [])
        if not isinstance(armed, list):
            violations.append(f"{account}:ARMED_SIGNALS_INVALID")
            armed = []
        for item in armed:
            if not isinstance(item, dict):
                violations.append(f"{account}:ARMED_SIGNAL_INVALID")
                continue
            checked_armed_signals += 1
            model_id = item.get("model_id")
            if model_id != account:
                violations.append(f"{account}:ARMED_MODEL_ID_DRIFT:{model_id}")
            forward_start = str(item.get("forward_test_start") or "")
            if expected_start and forward_start != expected_start:
                violations.append(
                    f"{account}:ARMED_FORWARD_START_DRIFT:{forward_start or 'MISSING'}"
                )
            if not _positive_finite(item.get("replay_max_price")):
                violations.append(f"{account}:ARMED_REPLAY_MAX_PRICE_INVALID")

        events = book.get("events", [])
        if not isinstance(events, list):
            violations.append(f"{account}:EVENTS_INVALID")
            continue
        for event in events:
            if not isinstance(event, dict) or _is_test_event(event):
                continue
            checked_strategy_events += 1
            model_id = event.get("model_id")
            if model_id != account:
                violations.append(f"{account}:STRATEGY_MODEL_ID_DRIFT:{model_id}")
            forward_start = str(event.get("forward_test_start") or "")
            if expected_start and forward_start != expected_start:
                violations.append(
                    f"{account}:STRATEGY_FORWARD_START_DRIFT:{forward_start or 'MISSING'}"
                )
            action = str(event.get("action") or "").upper()
            if action in ENTRY_ACTIONS and not _positive_finite(event.get("replay_max_price")):
                violations.append(f"{account}:ENTRY_REPLAY_MAX_PRICE_INVALID")

    return {
        "ok": not violations,
        "expected_forward_test_start": expected_start or None,
        "deployed_forward_test_start": deployed_start or None,
        "processor_state": runtime.get("state"),
        "processor_last_update_status": runtime.get("last_update_status"),
        "processor_last_modified": runtime.get("last_modified"),
        "latest_staging_deployment_found": deployment_found,
        "latest_staging_deployment_status": deployment_status,
        "latest_staging_deployment_conclusion": deployment_conclusion,
        "latest_staging_deployment_head_sha": deployment_head_sha,
        "latest_staging_deployment_run_id": deployment_run_id,
        "latest_staging_deployment_pending": deployment_pending,
        "checked_strategy_events": checked_strategy_events,
        "checked_armed_signals": checked_armed_signals,
        "violations": sorted(set(violations)),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "tradingview_mutation_attempted": False,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "",
        "### Shadow runtime / source-contract drift guard",
        f"Expected forward-test start: `{result.get('expected_forward_test_start') or 'missing'}`  ",
        f"Deployed forward-test start: `{result.get('deployed_forward_test_start') or 'missing'}`  ",
        f"Processor state/update: `{result.get('processor_state')}` / `{result.get('processor_last_update_status')}`  ",
    ]
    if result.get("latest_staging_deployment_found") is not None:
        status = result.get("latest_staging_deployment_status") or "missing"
        conclusion = result.get("latest_staging_deployment_conclusion") or "pending"
        run_id = result.get("latest_staging_deployment_run_id") or "missing"
        head_sha = result.get("latest_staging_deployment_head_sha") or "missing"
        lines.extend(
            [
                f"Latest staging deploy: `{status}` / `{conclusion}` (run `{run_id}`)  ",
                f"Latest staging deploy head: `{head_sha}`  ",
            ]
        )
        if result.get("latest_staging_deployment_pending") is True:
            lines.append(
                "Deployment convergence: **pending**; serialized staging deployment is still queued/running.  "
            )
    lines.extend(
        [
            f"Strategy events contract-checked: **{result.get('checked_strategy_events', 0)}**  ",
            f"ARMED signals contract-checked: **{result.get('checked_armed_signals', 0)}**",
        ]
    )
    violations = list(result.get("violations") or [])
    if violations:
        lines.extend(
            [
                "",
                "Contract drift: **FAIL-CLOSED**",
                *[f"- `{item}`" for item in violations],
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Contract drift: **none detected**. Validated TradingView configuration remains frozen; no mutation was attempted.",
            ]
        )
    return "\n".join(lines) + "\n"


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor-state", required=True)
    parser.add_argument("--runtime-contract", required=True)
    parser.add_argument("--deployment-status")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    deployment = _load(args.deployment_status) if args.deployment_status else None
    result = inspect_contract(
        _load(args.monitor_state),
        _load(args.runtime_contract),
        deployment,
    )
    Path(args.output_json).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
