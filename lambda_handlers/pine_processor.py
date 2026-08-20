"""AWS Lambda handler for fail-closed Pine and server-scanner paper processing."""

from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.armed_replay import (
    list_armed_ingress,
    list_recent_pine_event_state,
    replay_armed_events,
)
from daily_alpha.dynamo_ledger import DynamoPaperLedger
from daily_alpha.equity_liquidity import (
    LiquidityGatedPaperExecutor,
    S3ActionableLiquidityStore,
)
from daily_alpha.execution_universe import build_scanner_ingress
from daily_alpha.pine_paper_orchestrator import _all_open_trades
from daily_alpha.pine_processor import (
    DynamoPineEventStore,
    PineProcessorResult,
    process_sqs_batch,
)
from daily_alpha.reconciled_receipt_executor import (
    ReceiptReconciledAwsPinePaperExecutor,
)
from daily_alpha.shadow_routing import (
    PAPER_SHADOW_V24,
    PAPER_SHADOW_V25,
    ShadowRoutedPineEventStore,
    ShadowRoutedPinePaperExecutor,
    default_paper_account_id,
)


def _liquidity_store() -> S3ActionableLiquidityStore:
    return S3ActionableLiquidityStore()


def _replay_all_paper_accounts(*, now: datetime, limit: int) -> dict:
    accounts = [default_paper_account_id(), PAPER_SHADOW_V24, PAPER_SHADOW_V25]
    remaining = limit
    total_found = 0
    combined_counts: dict[str, int] = {}
    combined_outcomes: list[dict] = []
    scanned: list[str] = []

    for account_id in accounts:
        if remaining <= 0:
            break
        store = DynamoPineEventStore(account_id=account_id)
        executor = ShadowRoutedPinePaperExecutor(liquidity_store=_liquidity_store())
        result = replay_armed_events(store, executor, now=now, limit=remaining)
        scanned.append(account_id)
        found = int(result.get("armed_found", 0))
        total_found += found
        remaining -= found
        for disposition, count in dict(result.get("outcome_counts") or {}).items():
            combined_counts[str(disposition)] = (
                combined_counts.get(str(disposition), 0) + int(count)
            )
        for outcome in list(result.get("outcomes") or []):
            item = dict(outcome)
            item["paper_account_id"] = account_id
            combined_outcomes.append(item)

    return {
        "ok": True,
        "operation": "REPLAY_ARMED_SIGNALS",
        "processed_at": now.isoformat(),
        "accounts_scanned": scanned,
        "armed_found": total_found,
        "outcome_counts": combined_counts,
        "outcomes": combined_outcomes,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _shadow_monitor_state(
    *,
    now: datetime,
    armed_limit: int,
    event_limit: int,
) -> dict:
    """Return a read-only snapshot of shadow positions, armed state and receipts."""
    books: dict[str, dict] = {}
    for account_id in (PAPER_SHADOW_V24, PAPER_SHADOW_V25):
        trades = _all_open_trades(DynamoPaperLedger(account_id=account_id))
        store = DynamoPineEventStore(account_id=account_id)
        armed = list_armed_ingress(store, limit=armed_limit)
        event_state = list_recent_pine_event_state(store, limit=event_limit)
        books[account_id] = {
            "open_count": len(trades),
            "open_positions": [trade.to_dict() for trade in trades],
            "armed_count_visible": len(armed),
            "armed_limit": armed_limit,
            "armed_limit_reached": len(armed) == armed_limit,
            "armed_signals": [
                {
                    "persisted_signal_id": item.get("_persisted_signal_id"),
                    "signal_id": item.get("signal_id"),
                    "symbol": item.get("symbol"),
                    "action": item.get("action"),
                    "model_id": item.get("model_id"),
                    "forward_test_start": item.get("forward_test_start"),
                    "received_at": item.get("received_at"),
                    "replay_max_price": item.get("replay_max_price"),
                }
                for item in armed
            ],
            **event_state,
        }
    return {
        "ok": True,
        "service": "daily-alpha-pine-processor",
        "operation": "GET_SHADOW_MONITOR_STATE",
        "snapshot_at": now.isoformat(),
        "books": books,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def lambda_handler(event, context):
    operation = str(event.get("operation", "")).strip().upper() if isinstance(event, dict) else ""

    if operation == "LIST_OPEN_PAPER_POSITIONS":
        trades = _all_open_trades(DynamoPaperLedger())
        return {
            "ok": True,
            "service": "daily-alpha-pine-processor",
            "operation": operation,
            "open_count": len(trades),
            "open_positions": [trade.to_dict() for trade in trades],
            "trading_authorized": False,
            "live_trading_enabled": False,
            "request_id": getattr(context, "aws_request_id", None),
        }

    if operation == "LIST_SHADOW_PAPER_POSITIONS":
        books = {}
        for account_id in (PAPER_SHADOW_V24, PAPER_SHADOW_V25):
            trades = _all_open_trades(DynamoPaperLedger(account_id=account_id))
            books[account_id] = {
                "open_count": len(trades),
                "open_positions": [trade.to_dict() for trade in trades],
            }
        return {
            "ok": True,
            "service": "daily-alpha-pine-processor",
            "operation": operation,
            "books": books,
            "trading_authorized": False,
            "live_trading_enabled": False,
            "request_id": getattr(context, "aws_request_id", None),
        }

    if operation == "GET_SHADOW_MONITOR_STATE":
        now = datetime.now(UTC)
        try:
            armed_limit = int(event.get("armed_limit", 25))
            event_limit = int(event.get("event_limit", 100))
            result = _shadow_monitor_state(
                now=now,
                armed_limit=armed_limit,
                event_limit=event_limit,
            )
            return {
                **result,
                "request_id": getattr(context, "aws_request_id", None),
            }
        except Exception as exc:  # noqa: BLE001 - monitor boundary must fail closed
            return {
                "ok": False,
                "service": "daily-alpha-pine-processor",
                "operation": operation,
                "status": "REJECTED",
                "error_code": str(exc) or type(exc).__name__,
                "trading_authorized": False,
                "live_trading_enabled": False,
                "request_id": getattr(context, "aws_request_id", None),
            }

    if operation == "REPLAY_ARMED_SIGNALS":
        now = datetime.now(UTC)
        try:
            raw_limit = event.get("limit", 25)
            limit = int(raw_limit)
            result = _replay_all_paper_accounts(now=now, limit=limit)
            return {
                "service": "daily-alpha-pine-processor",
                **result,
                "request_id": getattr(context, "aws_request_id", None),
            }
        except Exception as exc:  # noqa: BLE001 - replay boundary must fail closed
            return {
                "ok": False,
                "service": "daily-alpha-pine-processor",
                "operation": operation,
                "status": "REJECTED",
                "error_code": str(exc) or type(exc).__name__,
                "trading_authorized": False,
                "live_trading_enabled": False,
                "request_id": getattr(context, "aws_request_id", None),
            }

    if operation == "EXECUTE_SCANNER_SIGNAL":
        now = datetime.now(UTC)
        try:
            raw_signal = event.get("signal")
            if not isinstance(raw_signal, dict):
                raise TypeError("SCANNER_SIGNAL_REQUIRED")
            ingress = build_scanner_ingress(raw_signal, received_at=now)
            processor_result = PineProcessorResult(
                schema_version="2026-08-17-scanner-v1",
                signal_id=str(ingress["signal_id"]),
                symbol=str(ingress["symbol"]),
                action=str(ingress["action"]),
                disposition="HELD_FOR_CONTEXT",
                reason="SCANNER_SIGNAL_REQUIRES_PAPER_CONTEXT",
                received_at=str(ingress["received_at"]),
                processed_at=now.isoformat(),
                position_fraction=ingress.get("position_fraction"),
                runner_stage=ingress.get("runner_stage"),
            )
            store = DynamoPineEventStore()
            persisted = store.persist(ingress, processor_result)
            executor = LiquidityGatedPaperExecutor(
                ReceiptReconciledAwsPinePaperExecutor(),
                _liquidity_store(),
            )
            execution = executor.execute(ingress, now=now)
            store.mark_execution(processor_result.signal_id, execution)
            return {
                "ok": True,
                "service": "daily-alpha-pine-processor",
                "operation": operation,
                "source": ingress["source"],
                "signal_id": processor_result.signal_id,
                "symbol": processor_result.symbol,
                "action": processor_result.action,
                "audit_persisted": persisted,
                "execution": execution,
                "trading_authorized": False,
                "live_trading_enabled": False,
                "request_id": getattr(context, "aws_request_id", None),
            }
        except Exception as exc:  # noqa: BLE001 - scanner boundary must fail closed
            return {
                "ok": False,
                "service": "daily-alpha-pine-processor",
                "operation": operation,
                "status": "REJECTED",
                "error_code": str(exc) or type(exc).__name__,
                "trading_authorized": False,
                "live_trading_enabled": False,
                "request_id": getattr(context, "aws_request_id", None),
            }

    store = ShadowRoutedPineEventStore()
    executor = ShadowRoutedPinePaperExecutor(liquidity_store=_liquidity_store())
    return process_sqs_batch(event, store, executor=executor)
