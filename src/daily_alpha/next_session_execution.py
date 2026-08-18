"""Run staged Daily Alpha actions during the next regular market session."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .execution_queue import (
    CANCEL_STATUS,
    PENDING_STATUS,
    RETRY_STATUS,
    WAIT_STATUS,
    prepare_next_session_signal,
)
from .execution_universe import ScannerState, execution_succeeded, load_state, write_state
from .orats import OratsClient, OratsError

DEFAULT_BUCKET = "daily-alpha-staging-490809405132-us-east-2"
LATEST_PREFIX = "daily-alpha/execution-universe/latest"
LEGACY_HUMAN_APPROVAL_STATUS = "PENDING_HUMAN_APPROVAL"


class UnsafeExecutionError(RuntimeError):
    """Raised when a downstream response violates the paper-only safety contract."""


def run_next_session_execution(
    *,
    mode: str,
    bucket: str,
    token: str,
    workdir: str | Path,
    now: datetime | None = None,
    s3_client: Any | None = None,
    lambda_client: Any | None = None,
    orats_client: OratsClient | None = None,
    run_id: str = "manual",
) -> dict[str, Any]:
    """Revalidate staged actions and route valid ones to the paper-only processor."""
    if mode not in {"morning_primary", "morning_retry"}:
        raise ValueError("Execution mode must be morning_primary or morning_retry")
    timestamp = _aware(now or datetime.now(UTC))
    if not token.strip():
        raise ValueError("ORATS token is required")

    if s3_client is None or lambda_client is None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - workflow installs boto3
            raise RuntimeError("BOTO3_UNAVAILABLE") from exc
        if s3_client is None:
            s3_client = boto3.client("s3")
        if lambda_client is None:
            lambda_client = boto3.client("lambda")

    orats = orats_client or OratsClient(
        token=token,
        mode="delayed",
        max_age_minutes=25,
    )

    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    pending_path = work / "pending_actions.json"
    state_path = work / "state.json"
    watch_json = work / "active_watch.json"
    _download_optional(
        s3_client,
        bucket,
        f"{LATEST_PREFIX}/pending_actions.json",
        pending_path,
        {"schema_version": "2026-08-17-pending-v1", "actions": []},
    )
    _download_optional(s3_client, bucket, f"{LATEST_PREFIX}/state.json", state_path, {})
    _download_optional(s3_client, bucket, f"{LATEST_PREFIX}/active_watch.json", watch_json, [])

    pending_doc = json.loads(pending_path.read_text(encoding="utf-8"))
    actions = list(pending_doc.get("actions") or [])
    state = load_state(state_path)
    watch_by_symbol = _load_watch(watch_json)

    attempted = 0
    executed = 0
    cancelled = 0
    deferred_data_error = 0
    remaining: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    for raw_item in actions:
        item = dict(raw_item)
        symbol = str(item.get("symbol", "")).strip().upper()
        action = str(item.get("action", "")).strip().upper()
        if not symbol or not action:
            continue
        attempted += 1
        record: dict[str, Any] = {
            "symbol": symbol,
            "action": action,
            "origin_market_date": item.get("market_date"),
            "mode": mode,
            "execution_authority": "AUTONOMOUS_PAPER_ONLY",
        }

        # Compatibility migration for actions stamped by the former manual-approval
        # gate. Paper execution is autonomous; the downstream paper executor owns
        # the hard 0.50% NAV ceiling plus lifecycle sizing and portfolio-risk gates.
        if str(item.get("status", "")).upper() == LEGACY_HUMAN_APPROVAL_STATUS:
            item["status"] = PENDING_STATUS
            record["legacy_status_normalized"] = LEGACY_HUMAN_APPROVAL_STATUS

        try:
            chain = orats.fetch_chain(symbol, as_of=timestamp)
            stock_price = float(chain.stock_price)
            if stock_price <= 0:
                raise ValueError("ORATS underlying stock price is unavailable")
            record["orats_observed_at"] = chain.observed_at.isoformat()
            record["stock_price"] = stock_price
            prepared = prepare_next_session_signal(
                item,
                stock_price=stock_price,
                now=timestamp,
            )
            record["revalidation"] = prepared.to_dict()

            if prepared.status == WAIT_STATUS:
                remaining.append(item)
                record["final_status"] = WAIT_STATUS
                attempts.append(record)
                continue
            if prepared.status == CANCEL_STATUS:
                cancelled += 1
                record["final_status"] = CANCEL_STATUS
                attempts.append(record)
                _update_watch(
                    watch_by_symbol,
                    symbol,
                    scanner_status=prepared.reason,
                    execution=CANCEL_STATUS,
                )
                continue

            executable_signal = dict(prepared.signal or {})
            # Do not forward obsolete manual-approval metadata. Sizing and risk are
            # derived by the autonomous paper executor from configured NAV, lifecycle,
            # portfolio state, and fresh market data.
            executable_signal.pop("human_approval", None)
            executable_signal.pop("approved_risk_fraction", None)
            outcome = _invoke_processor(lambda_client, executable_signal)
            record["processor"] = outcome
            if outcome.get("ok") is not True:
                raise RuntimeError(str(outcome.get("error_code", "PROCESSOR_REJECTED")))
            execution = outcome.get("execution", {})
            if execution_succeeded(execution):
                executed += 1
                record["final_status"] = "EXECUTED_PAPER"
                if action == "EXIT":
                    state.pop(symbol, None)
                    position = "FLAT"
                else:
                    after = item.get("state_after")
                    if isinstance(after, dict):
                        state[symbol] = ScannerState.from_dict(after)
                    position = "OPEN"
                current = state.get(symbol)
                _update_watch(
                    watch_by_symbol,
                    symbol,
                    position=position,
                    runner_stage=current.runner_stage if current else "",
                    scanner_status="NEXT_SESSION_REVALIDATED",
                    execution="EXECUTED_PAPER",
                )
            else:
                cancelled += 1
                disposition = str(execution.get("disposition", "NO_TRADE"))
                reason = str(execution.get("reason", disposition))
                record["final_status"] = disposition
                record["reason"] = reason
                _update_watch(
                    watch_by_symbol,
                    symbol,
                    scanner_status=reason,
                    execution=disposition,
                )
            attempts.append(record)
        except UnsafeExecutionError:
            raise
        except (OratsError, RuntimeError, ValueError, TypeError) as exc:
            deferred_data_error += 1
            retry_item = dict(item)
            retry_item["status"] = RETRY_STATUS
            retry_item["attempt_count"] = int(item.get("attempt_count", 0)) + 1
            retry_item["last_attempt_at"] = timestamp.isoformat()
            retry_item["last_error"] = f"{type(exc).__name__}:{exc}"
            remaining.append(retry_item)
            record["error"] = retry_item["last_error"]
            record["final_status"] = RETRY_STATUS
            attempts.append(record)
            _update_watch(
                watch_by_symbol,
                symbol,
                scanner_status=RETRY_STATUS,
                execution=RETRY_STATUS,
            )
        time.sleep(0.35)

    write_state(state_path, state)
    pending_doc["last_execution_attempt_at"] = timestamp.isoformat()
    pending_doc["actions"] = remaining
    pending_path.write_text(json.dumps(pending_doc, indent=2, sort_keys=True), encoding="utf-8")

    watch = sorted(
        watch_by_symbol.values(),
        key=lambda row: (
            int(row.get("rank")) if str(row.get("rank", "")).isdigit() else 999999,
            str(row.get("symbol", "")),
        ),
    )
    watch_json.write_text(json.dumps(watch, indent=2, sort_keys=True), encoding="utf-8")
    watch_csv = work / "active_watch.csv"
    _write_watch_csv(watch_csv, watch)

    audit = {
        "schema_version": "2026-08-17-next-session-v1",
        "generated_at": timestamp.isoformat(),
        "execution_mode": mode,
        "paper_execution_mode": "AUTONOMOUS_PAPER_ONLY",
        "attempted": attempted,
        "executed_paper": executed,
        "cancelled_or_no_trade": cancelled,
        "deferred_data_error": deferred_data_error,
        "remaining_pending": len(remaining),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "attempts": attempts,
    }
    audit_path = work / "morning_execution_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")

    history = f"daily-alpha/execution-universe/history/{run_id}-morning"
    for path in (state_path, pending_path, watch_json, watch_csv, audit_path):
        s3_client.upload_file(str(path), bucket, f"{LATEST_PREFIX}/{path.name}")
        s3_client.upload_file(str(path), bucket, f"{history}/{path.name}")
    return audit


def _download_optional(
    client: Any,
    bucket: str,
    key: str,
    path: Path,
    default: Any,
) -> None:
    try:
        client.download_file(bucket, key, str(path))
    except Exception as exc:
        code = _aws_error_code(exc)
        if code not in {"404", "NoSuchKey", "NotFound"}:
            raise
        path.write_text(json.dumps(default), encoding="utf-8")


def _load_watch(path: Path) -> dict[str, dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        rows = []
    if not isinstance(rows, list):
        rows = []
    return {
        str(row.get("symbol", "")).upper(): dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def _update_watch(
    watch: dict[str, dict[str, Any]],
    symbol: str,
    **updates: Any,
) -> None:
    row = watch.setdefault(symbol, {"symbol": symbol})
    row.update(updates)


def _write_watch_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "rank",
        "symbol",
        "label",
        "position",
        "runner_stage",
        "scanner_status",
        "action",
        "execution",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _invoke_processor(client: Any, signal: dict[str, Any] | None) -> dict[str, Any]:
    if signal is None:
        raise ValueError("Executable next-session signal is required")
    response = client.invoke(
        FunctionName="daily-alpha-pine-processor",
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {"operation": "EXECUTE_SCANNER_SIGNAL", "signal": signal}
        ).encode("utf-8"),
    )
    raw = response["Payload"].read().decode("utf-8")
    body = json.loads(raw or "{}")
    if response.get("FunctionError"):
        raise RuntimeError(f"Pine processor FunctionError: {body}")
    if body.get("live_trading_enabled") is not False:
        raise UnsafeExecutionError(f"Unsafe live trading response: {body}")
    return body


def _aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=["morning_primary", "morning_retry"])
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--workdir", default="data/execution-universe-morning")
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", "manual"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    audit = run_next_session_execution(
        mode=args.mode,
        bucket=args.bucket,
        token=os.getenv("ORATS_TOKEN", ""),
        workdir=args.workdir,
        run_id=args.run_id,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"attempted={audit['attempted']}\n")
            handle.write(f"executed={audit['executed_paper']}\n")
            handle.write(f"cancelled={audit['cancelled_or_no_trade']}\n")
            handle.write(f"deferred={audit['deferred_data_error']}\n")
            handle.write(f"remaining={audit['remaining_pending']}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())