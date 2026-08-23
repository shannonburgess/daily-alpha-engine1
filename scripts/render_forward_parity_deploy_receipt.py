from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROJECTION_MINIMUM_COMMIT = "32b4626a9b1138d4a1e9788f533d6a06ac5f929a"
RECEIPT_SCHEMA = "DAILY_ALPHA_FORWARD_PARITY_DEPLOYMENT_RECEIPT_V1"
EXPECTED_BOOKS = ("PAPER_SHADOW_V24", "PAPER_SHADOW_V25")
SANITIZED_EVENT_FIELDS = (
    "signal_id",
    "symbol",
    "action",
    "source",
    "strategy",
    "strategy_version",
    "model_id",
    "timeframe",
    "price",
    "bar_time",
    "entry_type",
    "runner_stage",
    "position_fraction",
    "earnings_gap_class",
    "stock_stop_price",
    "average_daily_dollar_volume",
    "breakout_level",
    "armed_age",
    "exit_reason",
    "forward_test_start",
    "replay_max_price",
    "received_at",
    "disposition",
    "reason",
    "paper_execution_triggered",
    "paper_ledger_updated",
    "trading_authorized",
    "live_trading_enabled",
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReceiptError(ValueError):
    """Sanitized deployment evidence is incomplete or inconsistent."""


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptError(f"{field} must be an object")
    return value


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReceiptError(f"{field} is required")
    return text


def _required_sha(value: Any, field: str) -> str:
    text = _required_text(value, field).lower()
    if not _SHA_RE.fullmatch(text):
        raise ReceiptError(f"{field} must be a full 40-character Git SHA")
    return text


def _sanitize_event(raw_event: Any, account_id: str, index: int) -> dict[str, Any]:
    event = _required_mapping(raw_event, f"{account_id}.events[{index}]")
    signal_id = _required_text(event.get("signal_id"), f"{account_id}.events[{index}].signal_id")
    sanitized = {
        field: event[field]
        for field in SANITIZED_EVENT_FIELDS
        if field in event
    }
    sanitized["signal_id"] = signal_id
    if sanitized.get("trading_authorized") is True:
        raise ReceiptError(f"{account_id} event trading_authorized must remain false")
    if sanitized.get("live_trading_enabled") is True:
        raise ReceiptError(f"{account_id} event live_trading_enabled must remain false")
    return sanitized


def _book_summary(raw_book: Any, account_id: str) -> dict[str, Any]:
    book = _required_mapping(raw_book, account_id)
    events = book.get("events")
    if not isinstance(events, list):
        raise ReceiptError(f"{account_id}.events must be a list")
    if bool(book.get("scan_truncated")):
        raise ReceiptError(f"{account_id} event scan is truncated")

    visible = int(book.get("event_count_visible", len(events)))
    if visible != len(events):
        raise ReceiptError(f"{account_id} event_count_visible does not match events")

    open_positions = book.get("open_positions")
    armed_signals = book.get("armed_signals")
    if not isinstance(open_positions, list):
        raise ReceiptError(f"{account_id}.open_positions must be a list")
    if not isinstance(armed_signals, list):
        raise ReceiptError(f"{account_id}.armed_signals must be a list")

    return {
        "event_count_visible": visible,
        "events": tuple(
            _sanitize_event(event, account_id, index) for index, event in enumerate(events)
        ),
        "open_count": int(book.get("open_count", len(open_positions))),
        "armed_count_visible": int(book.get("armed_count_visible", len(armed_signals))),
        "scan_truncated": False,
    }


def build_receipt(
    monitor: Mapping[str, Any],
    processor_config: Mapping[str, Any],
    *,
    commit_sha: str,
    run_id: str,
    run_attempt: str,
    repository: str,
    projection_ancestor_verified: bool,
) -> dict[str, Any]:
    commit = _required_sha(commit_sha, "commit_sha")
    if not projection_ancestor_verified:
        raise ReceiptError("forward parity projection ancestry was not verified")
    if monitor.get("ok") is not True:
        raise ReceiptError("shadow monitor did not return ok=true")
    if monitor.get("operation") != "GET_SHADOW_MONITOR_STATE":
        raise ReceiptError("unexpected shadow monitor operation")
    if monitor.get("trading_authorized") is not False:
        raise ReceiptError("shadow monitor trading_authorized must remain false")
    if monitor.get("live_trading_enabled") is not False:
        raise ReceiptError("shadow monitor live_trading_enabled must remain false")

    books = _required_mapping(monitor.get("books"), "books")
    if set(books) != set(EXPECTED_BOOKS):
        raise ReceiptError("shadow monitor books are not exactly SH24 and SH25")

    if processor_config.get("LastUpdateStatus") != "Successful":
        raise ReceiptError("Pine processor LastUpdateStatus must be Successful")
    if processor_config.get("Handler") != "lambda_handlers.pine_processor.lambda_handler":
        raise ReceiptError("Pine processor handler is not canonical")

    code_sha256 = _required_text(processor_config.get("CodeSha256"), "processor CodeSha256")
    version = _required_text(processor_config.get("Version"), "processor Version")

    return {
        "schema": RECEIPT_SCHEMA,
        "repository": _required_text(repository, "repository"),
        "commit_sha": commit,
        "workflow_run_id": _required_text(run_id, "workflow_run_id"),
        "workflow_run_attempt": _required_text(run_attempt, "workflow_run_attempt"),
        "projection_minimum_commit": PROJECTION_MINIMUM_COMMIT,
        "projection_ancestor_verified": True,
        "processor": {
            "function_name": _required_text(
                processor_config.get("FunctionName"), "processor FunctionName"
            ),
            "handler": processor_config["Handler"],
            "runtime": _required_text(processor_config.get("Runtime"), "processor Runtime"),
            "version": version,
            "code_sha256": code_sha256,
            "last_update_status": processor_config["LastUpdateStatus"],
        },
        "books": {
            account_id: _book_summary(books[account_id], account_id)
            for account_id in EXPECTED_BOOKS
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def render_markdown(receipt: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(receipt), sort_keys=True, separators=(",", ":"))
    return (
        f"<!-- {RECEIPT_SCHEMA} -->\n"
        "## Forward parity staging deployment receipt\n\n"
        "The deployed staging Pine processor passed the read-only SH24/SH25 monitor contract "
        "and the deployed commit was verified to contain the merged forward-parity projection. "
        "The receipt includes only the persisted event fields needed for book/forward-parity "
        "inspection; webhook secrets and raw ingress are excluded. This is deployment evidence "
        "only; it does not prove signal parity or authorize trading.\n\n"
        f"```json\n{encoded}\n```\n"
    )


def _load_json(path: str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text())
    return _required_mapping(payload, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor", required=True)
    parser.add_argument("--processor-config", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown", required=True)
    args = parser.parse_args()

    receipt = build_receipt(
        _load_json(args.monitor),
        _load_json(args.processor_config),
        commit_sha=os.environ.get("GITHUB_SHA", ""),
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        projection_ancestor_verified=os.environ.get("PARITY_PROJECTION_ANCESTOR_VERIFIED") == "true",
    )
    Path(args.output_json).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    Path(args.output_markdown).write_text(render_markdown(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
