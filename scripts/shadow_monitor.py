"""Summarize Daily Alpha SH24/SH25 paper-shadow state from read-only AWS evidence."""

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
MAX_RENDERED_EVENTS_PER_ACCOUNT = 10
TEST_SIGNAL_MARKERS = ("E2E", "CONNECTIVITY", "SYSTEM-ROUNDTRIP", "STAGING-READINESS")


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _session_events(events: list[dict[str, Any]], session_date: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for event in events:
        received = _parse_time(event.get("received_at"))
        if received and received.astimezone(NEW_YORK).date().isoformat() == session_date:
            selected.append(event)
    return selected


def _is_test_event(event: dict[str, Any]) -> bool:
    signal_id = str(event.get("signal_id") or "").upper()
    symbol = str(event.get("symbol") or "").upper()
    return any(marker in signal_id for marker in TEST_SIGNAL_MARKERS) or symbol == "DAE2E"


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": event.get("signal_id"),
        "symbol": event.get("symbol"),
        "action": event.get("action"),
        "model_id": event.get("model_id"),
        "received_at": event.get("received_at"),
        "evaluated_at": event.get("evaluated_at"),
        "disposition": event.get("disposition"),
        "reason": event.get("reason"),
        "paper_execution_triggered": event.get("paper_execution_triggered") is True,
        "evidence_type": "TEST_PROOF" if _is_test_event(event) else "STRATEGY",
    }


def _safety_violations(state: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if state.get("trading_authorized") is not False:
        violations.append("MONITOR_TRADING_AUTHORIZED_NOT_FALSE")
    if state.get("live_trading_enabled") is not False:
        violations.append("MONITOR_LIVE_TRADING_NOT_FALSE")

    books = state.get("books")
    if not isinstance(books, dict):
        return [*violations, "MONITOR_BOOKS_MISSING"]

    for account in SHADOW_ACCOUNTS:
        book = books.get(account)
        if not isinstance(book, dict):
            violations.append(f"{account}:BOOK_MISSING")
            continue
        if book.get("scan_truncated") is True:
            violations.append(f"{account}:EVENT_EVIDENCE_TRUNCATED")
        events = book.get("events", [])
        if not isinstance(events, list):
            violations.append(f"{account}:EVENTS_INVALID")
            continue
        for event in events:
            if not isinstance(event, dict):
                violations.append(f"{account}:EVENT_INVALID")
                continue
            model_id = event.get("model_id")
            if model_id not in (None, "", account):
                violations.append(f"{account}:MODEL_ID_MISMATCH:{model_id}")
            paper_account = event.get("paper_account_id")
            if paper_account not in (None, "", account):
                violations.append(f"{account}:EXECUTION_ACCOUNT_MISMATCH:{paper_account}")
            if event.get("trading_authorized", False) is not False:
                violations.append(f"{account}:TRADING_AUTHORIZED_NOT_FALSE")
            if event.get("live_trading_enabled", False) is not False:
                violations.append(f"{account}:LIVE_TRADING_NOT_FALSE")
            receipt = event.get("execution_receipt")
            if isinstance(receipt, dict):
                receipt_account = receipt.get("account_id")
                if receipt_account not in (None, "", account):
                    violations.append(
                        f"{account}:RECEIPT_ACCOUNT_MISMATCH:{receipt_account}"
                    )
    return sorted(set(violations))


def summarize(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Build one exact read-only shadow status from GET_SHADOW_MONITOR_STATE."""
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    session_date = timestamp.astimezone(NEW_YORK).date().isoformat()
    violations = _safety_violations(state)

    books = state.get("books") if isinstance(state.get("books"), dict) else {}
    accounts: dict[str, Any] = {}
    total_strategy_events = 0
    total_test_events = 0
    total_strategy_fills = 0
    total_armed = 0
    strategy_reasons: Counter[str] = Counter()

    for account in SHADOW_ACCOUNTS:
        book = books.get(account, {}) if isinstance(books, dict) else {}
        events = book.get("events", []) if isinstance(book, dict) else []
        if not isinstance(events, list):
            events = []
        typed_events = [event for event in events if isinstance(event, dict)]
        session_events = _session_events(typed_events, session_date)
        session_events.sort(
            key=lambda event: _parse_time(event.get("received_at"))
            or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        test_events = [event for event in session_events if _is_test_event(event)]
        strategy_events = [event for event in session_events if not _is_test_event(event)]
        strategy_fills = [
            event for event in strategy_events if event.get("disposition") == "EXECUTED_PAPER"
        ]
        receipts = [
            event["execution_receipt"]
            for event in strategy_events
            if isinstance(event.get("execution_receipt"), dict)
        ]
        reasons = Counter(
            str(event.get("reason") or event.get("disposition") or "UNKNOWN")
            for event in strategy_events
        )
        strategy_reasons.update(reasons)
        total_strategy_events += len(strategy_events)
        total_test_events += len(test_events)
        total_strategy_fills += len(strategy_fills)
        armed_count = int(book.get("armed_count_visible", 0)) if isinstance(book, dict) else 0
        total_armed += armed_count
        latest = max(
            (_parse_time(event.get("received_at")) for event in typed_events),
            default=None,
            key=lambda value: value or datetime.min.replace(tzinfo=UTC),
        )
        open_positions = book.get("open_positions", []) if isinstance(book, dict) else []
        if not isinstance(open_positions, list):
            open_positions = []

        accounts[account] = {
            "open_count": int(book.get("open_count", len(open_positions)))
            if isinstance(book, dict)
            else len(open_positions),
            "open_positions": open_positions,
            "armed_count": armed_count,
            "session_strategy_event_count": len(strategy_events),
            "session_test_event_count": len(test_events),
            "session_fill_count": len(strategy_fills),
            "session_strategy_events": [_compact_event(event) for event in strategy_events],
            "session_test_events": [_compact_event(event) for event in test_events],
            "session_receipts": receipts,
            "reason_counts": dict(sorted(reasons.items())),
            "latest_event_at": latest.isoformat() if latest else None,
            "event_evidence_truncated": bool(book.get("scan_truncated"))
            if isinstance(book, dict)
            else True,
        }

    if violations:
        diagnosis = "SAFETY_OR_EVIDENCE_VIOLATION"
    elif total_strategy_fills:
        diagnosis = "TRADES_RECORDED"
    elif total_strategy_events:
        diagnosis = "STRATEGY_EVENTS_RECEIVED_NO_PAPER_FILL"
    elif total_armed:
        diagnosis = "ARMED_WAITING_FOR_REVALIDATION"
    else:
        diagnosis = "NO_GENUINE_STRATEGY_EVENT_RECEIVED"

    return {
        "ok": not violations,
        "snapshot_at": timestamp.isoformat(),
        "session_date_et": session_date,
        "diagnosis": diagnosis,
        "total_strategy_events": total_strategy_events,
        "total_test_events": total_test_events,
        "total_session_fills": total_strategy_fills,
        "total_armed": total_armed,
        "blocker_counts": dict(sorted(strategy_reasons.items())),
        "accounts": accounts,
        "safety": {
            "trading_authorized": False if not violations else state.get("trading_authorized"),
            "live_trading_enabled": False if not violations else state.get("live_trading_enabled"),
            "violations": violations,
        },
        "tradingview_configuration_frozen": True,
        "tradingview_mutation_attempted": False,
    }


def _render_events(lines: list[str], title: str, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    lines.append(title)
    for event in events[:MAX_RENDERED_EVENTS_PER_ACCOUNT]:
        lines.append(
            "- "
            f"`{event.get('received_at')}` "
            f"`{event.get('signal_id')}` "
            f"{event.get('symbol') or '?'} {event.get('action') or '?'} -> "
            f"`{event.get('disposition') or '?'}` / "
            f"`{event.get('reason') or '?'}`"
        )


def render_markdown(summary: dict[str, Any]) -> str:
    """Render a concise rolling issue comment and workflow summary."""
    lines = [
        "<!-- daily-alpha-shadow-monitor -->",
        "## Daily Alpha PAPER Shadow Monitor",
        "",
        f"**Session:** {summary['session_date_et']} ET  ",
        f"**Diagnosis:** `{summary['diagnosis']}`  ",
        f"**Genuine SH24/SH25 strategy events today:** {summary['total_strategy_events']}  ",
        f"**Test/proof events today:** {summary['total_test_events']}  ",
        f"**Paper fills today:** {summary['total_session_fills']}  ",
        f"**Currently ARMED:** {summary['total_armed']}  ",
        "**Safety:** `trading_authorized=false`, `live_trading_enabled=false`",
        "",
    ]

    for account in SHADOW_ACCOUNTS:
        state = summary["accounts"][account]
        lines.extend(
            [
                f"### {account}",
                f"Open positions: **{state['open_count']}**  ",
                f"ARMED: **{state['armed_count']}**  ",
                f"Genuine strategy events today: **{state['session_strategy_event_count']}**  ",
                f"Test/proof events today: **{state['session_test_event_count']}**  ",
                f"Fills today: **{state['session_fill_count']}**  ",
                f"Latest durable event: `{state['latest_event_at'] or 'none observed'}`",
            ]
        )
        if state["reason_counts"]:
            reasons = ", ".join(
                f"`{reason}`={count}" for reason, count in state["reason_counts"].items()
            )
            lines.append(f"Genuine strategy blockers/outcomes: {reasons}")
        _render_events(lines, "Recent genuine strategy events:", state["session_strategy_events"])
        _render_events(lines, "Test/proof traffic (excluded from trade diagnosis):", state["session_test_events"])
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
        lines.extend(["### Exact genuine-strategy no-fill evidence", blockers, ""])
    elif summary["diagnosis"] == "NO_GENUINE_STRATEGY_EVENT_RECEIVED":
        lines.extend(
            [
                "### Exact genuine-strategy no-fill evidence",
                "No genuine SH24/SH25 strategy-origin event reached the durable staging store for this ET session. Any E2E/connectivity proof traffic is shown separately and excluded from the trade diagnosis. This does not prove a TradingView defect; it proves only that no genuine strategy order event reached AWS. TradingView configuration remains frozen.",
                "",
            ]
        )

    violations = summary["safety"]["violations"]
    if violations:
        lines.extend(["### FAIL-CLOSED MONITOR VIOLATION", *[f"- `{item}`" for item in violations], ""])

    lines.append(f"Last automated snapshot: `{summary['snapshot_at']}`")
    return "\n".join(lines) + "\n"


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor-state", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    summary = summarize(_load(args.monitor_state))
    Path(args.output_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(summary))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
