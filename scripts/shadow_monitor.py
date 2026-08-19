#!/usr/bin/env python3
"""Summarize Daily Alpha SH24/SH25 paper-shadow state from read-only AWS evidence.

This module never mutates trading state. It consumes the existing read-only shadow
position response plus DynamoDB scan exports for the two isolated Pine-event books
and emits one machine-readable status and one concise Markdown status.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHADOW_ACCOUNTS = ("PAPER_SHADOW_V24", "PAPER_SHADOW_V25")
NEW_YORK = ZoneInfo("America/New_York")


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _ddb_text(item: dict[str, Any], name: str) -> str | None:
    value = item.get(name)
    if not isinstance(value, dict):
        return None
    text = value.get("S")
    return str(text) if text is not None else None


def _json_text(item: dict[str, Any], name: str) -> dict[str, Any] | None:
    raw = _ddb_text(item, name)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def decode_events(scan_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Decode the Pine-event fields used by monitoring from an AWS scan response."""
    decoded: list[dict[str, Any]] = []
    for item in scan_payload.get("Items", []):
        if not isinstance(item, dict):
            continue
        ingress = _json_text(item, "ingress_json") or {}
        result = _json_text(item, "result_json") or {}
        execution = _json_text(item, "execution_json") or {}
        decoded.append(
            {
                "signal_id": _ddb_text(item, "signal_id") or ingress.get("signal_id"),
                "symbol": _ddb_text(item, "symbol") or ingress.get("symbol"),
                "action": _ddb_text(item, "action") or ingress.get("action"),
                "disposition": _ddb_text(item, "disposition")
                or execution.get("disposition")
                or result.get("disposition"),
                "reason": _ddb_text(item, "reason")
                or execution.get("reason")
                or result.get("reason"),
                "received_at": ingress.get("received_at") or result.get("received_at"),
                "model_id": ingress.get("model_id"),
                "forward_test_start": ingress.get("forward_test_start"),
                "replay_max_price": ingress.get("replay_max_price"),
                "execution": execution,
            }
        )
    return decoded


def _session_events(events: list[dict[str, Any]], session_date: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for event in events:
        received = _parse_time(event.get("received_at"))
        if received and received.astimezone(NEW_YORK).date().isoformat() == session_date:
            selected.append(event)
    return selected


def _receipt(event: dict[str, Any]) -> dict[str, Any] | None:
    execution = event.get("execution")
    if not isinstance(execution, dict):
        return None
    receipt = execution.get("execution_receipt")
    return receipt if isinstance(receipt, dict) else None


def _safety_violations(
    positions: dict[str, Any], events_by_account: dict[str, list[dict[str, Any]]]
) -> list[str]:
    violations: list[str] = []
    if positions.get("trading_authorized") is not False:
        violations.append("POSITIONS_TRADING_AUTHORIZED_NOT_FALSE")
    if positions.get("live_trading_enabled") is not False:
        violations.append("POSITIONS_LIVE_TRADING_NOT_FALSE")

    for account, events in events_by_account.items():
        for event in events:
            execution = event.get("execution")
            if not isinstance(execution, dict) or not execution:
                continue
            if execution.get("trading_authorized", False) is not False:
                violations.append(f"{account}:TRADING_AUTHORIZED_NOT_FALSE")
            if execution.get("live_trading_enabled", False) is not False:
                violations.append(f"{account}:LIVE_TRADING_NOT_FALSE")
            paper_account = execution.get("paper_account_id")
            if paper_account not in (None, "", account):
                violations.append(f"{account}:EXECUTION_ACCOUNT_MISMATCH:{paper_account}")
            receipt = _receipt(event)
            if receipt:
                receipt_account = receipt.get("account_id")
                if receipt_account not in (None, "", account):
                    violations.append(
                        f"{account}:RECEIPT_ACCOUNT_MISMATCH:{receipt_account}"
                    )
    return sorted(set(violations))


def summarize(
    positions: dict[str, Any],
    scans_by_account: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the canonical read-only shadow status used by the scheduled monitor."""
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    session_date = timestamp.astimezone(NEW_YORK).date().isoformat()

    events_by_account = {
        account: decode_events(scans_by_account.get(account, {}))
        for account in SHADOW_ACCOUNTS
    }
    violations = _safety_violations(positions, events_by_account)
    books = positions.get("books") if isinstance(positions.get("books"), dict) else {}

    account_summaries: dict[str, Any] = {}
    total_session_events = 0
    total_session_fills = 0
    all_reasons: Counter[str] = Counter()

    for account in SHADOW_ACCOUNTS:
        events = events_by_account[account]
        session_events = _session_events(events, session_date)
        receipts = [receipt for event in session_events if (receipt := _receipt(event))]
        fills = [
            event
            for event in session_events
            if isinstance(event.get("execution"), dict)
            and event["execution"].get("disposition") == "EXECUTED_PAPER"
        ]
        reason_counts = Counter(
            str(event.get("reason") or event.get("disposition") or "UNKNOWN")
            for event in session_events
        )
        all_reasons.update(reason_counts)
        total_session_events += len(session_events)
        total_session_fills += len(fills)

        latest = max(
            (_parse_time(event.get("received_at")) for event in events),
            default=None,
            key=lambda value: value or datetime.min.replace(tzinfo=UTC),
        )
        book = books.get(account, {}) if isinstance(books, dict) else {}
        open_positions = book.get("open_positions", []) if isinstance(book, dict) else []
        if not isinstance(open_positions, list):
            open_positions = []

        account_summaries[account] = {
            "open_count": int(book.get("open_count", len(open_positions)))
            if isinstance(book, dict)
            else len(open_positions),
            "open_positions": open_positions,
            "session_event_count": len(session_events),
            "session_fill_count": len(fills),
            "session_receipts": receipts,
            "reason_counts": dict(sorted(reason_counts.items())),
            "latest_event_at": latest.isoformat() if latest else None,
        }

    if violations:
        diagnosis = "SAFETY_OR_ISOLATION_VIOLATION"
    elif total_session_fills:
        diagnosis = "TRADES_RECORDED"
    elif total_session_events:
        diagnosis = "STRATEGY_EVENTS_RECEIVED_NO_PAPER_FILL"
    else:
        diagnosis = "NO_STRATEGY_EVENT_RECEIVED"

    return {
        "ok": not violations,
        "snapshot_at": timestamp.isoformat(),
        "session_date_et": session_date,
        "diagnosis": diagnosis,
        "total_session_events": total_session_events,
        "total_session_fills": total_session_fills,
        "blocker_counts": dict(sorted(all_reasons.items())),
        "accounts": account_summaries,
        "safety": {
            "trading_authorized": False if not violations else positions.get("trading_authorized"),
            "live_trading_enabled": False if not violations else positions.get("live_trading_enabled"),
            "violations": violations,
        },
        "tradingview_configuration_frozen": True,
        "tradingview_mutation_attempted": False,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    """Render one concise, rolling issue/status comment."""
    lines = [
        "<!-- daily-alpha-shadow-monitor -->",
        "## Daily Alpha PAPER Shadow Monitor",
        "",
        f"**Session:** {summary['session_date_et']} ET  ",
        f"**Diagnosis:** `{summary['diagnosis']}`  ",
        f"**Strategy events today:** {summary['total_session_events']}  ",
        f"**Paper fills today:** {summary['total_session_fills']}  ",
        "**Safety:** `trading_authorized=false`, `live_trading_enabled=false`",
        "",
    ]

    for account in SHADOW_ACCOUNTS:
        state = summary["accounts"][account]
        lines.extend(
            [
                f"### {account}",
                f"Open positions: **{state['open_count']}**  ",
                f"Events today: **{state['session_event_count']}**  ",
                f"Fills today: **{state['session_fill_count']}**  ",
                f"Latest durable event: `{state['latest_event_at'] or 'none observed'}`",
            ]
        )
        if state["reason_counts"]:
            reasons = ", ".join(
                f"`{reason}`={count}" for reason, count in state["reason_counts"].items()
            )
            lines.append(f"Outcomes/blockers: {reasons}")
        if state["session_receipts"]:
            lines.append("Receipts:")
            for receipt in state["session_receipts"]:
                symbol = receipt.get("symbol", "?")
                action = receipt.get("action", "?")
                quantity = receipt.get("quantity", receipt.get("fill_quantity", "?"))
                price = receipt.get("fill_price", "?")
                lines.append(f"- `{symbol}` {action}: qty={quantity}, fill={price}")
        lines.append("")

    if summary["blocker_counts"]:
        blockers = ", ".join(
            f"`{reason}`={count}" for reason, count in summary["blocker_counts"].items()
        )
        lines.extend(["### Exact no-fill / outcome evidence", blockers, ""])
    elif summary["diagnosis"] == "NO_STRATEGY_EVENT_RECEIVED":
        lines.extend(
            [
                "### Exact no-fill / outcome evidence",
                "No SH24/SH25 strategy-origin event reached the durable staging event store for this ET session. This is an observable no-event state, not an invented trade rejection. Alert/watchlist configuration remains frozen.",
                "",
            ]
        )

    violations = summary["safety"]["violations"]
    if violations:
        lines.extend(["### SAFETY VIOLATION", *[f"- `{item}`" for item in violations], ""])

    lines.append(f"Last automated snapshot: `{summary['snapshot_at']}`")
    return "\n".join(lines) + "\n"


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", required=True)
    parser.add_argument("--events-v24", required=True)
    parser.add_argument("--events-v25", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    summary = summarize(
        _load(args.positions),
        {
            "PAPER_SHADOW_V24": _load(args.events_v24),
            "PAPER_SHADOW_V25": _load(args.events_v25),
        },
    )
    Path(args.output_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(summary))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
