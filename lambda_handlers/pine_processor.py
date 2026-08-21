"""AWS Lambda handler for fail-closed Pine and server-scanner paper processing."""

from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.actionable_sector import (
    S3ActionableContextStore,
    attach_sector_evidence,
    enrich_entry_sector,
)
from daily_alpha.armed_replay import (
    list_armed_ingress,
    list_recent_pine_event_state,
    replay_armed_events,
)
from daily_alpha.dynamo_ledger import DynamoPaperLedger
from daily_alpha.equity_liquidity import LiquidityGatedPaperExecutor
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


def _liquidity_store() -> S3ActionableContextStore:
    return S3ActionableContextStore()


def _replay_all_paper_accounts(*, now: datetime, limit: int) -> dict:
    # Shadow forward-test books are operationally primary for issue #213. Scan
    # them before the legacy/default paper account so a large default backlog
    # cannot consume the global replay budget and starve SH24/SH25.
    accounts = [PAPER_SHADOW_V24, PAPER_SHADOW_V25, default_paper_account_id()]
    remaining = limit
    total_found = 0
    total_claimed = 0
    total_lease_conflicts = 0
    combined_counts: dict[str, int] = {}
    combined_outcomes: list[dict] = []
    scanned: list[str] = []
    account_results: list[dict] = []

    for account_id in accounts:
        if remaining <= 0:
            break
        store = DynamoPineEventStore(account_id=account_id)
        executor = ShadowRoutedPinePaperExecutor(liquidity_store=_liquidity_store())
        result = replay_armed_events(store, executor, now=now, limit=remaining)
        scanned.append(account_id)

        if result.get("ok") is not True:
            raise RuntimeError("ARMED_REPLAY_CHILD_RESULT_NOT_OK")
        if result.get("trading_authorized") is not False:
            raise RuntimeError("ARMED_REPLAY_CHILD_TRADING_AUTH_DRIFT")
        if result.get("live_trading_enabled") is not False:
            raise RuntimeError("ARMED_REPLAY_CHILD_LIVE_AUTH_DRIFT")

        found = int(result.get("armed_found", -1))
        claimed = int(result.get("armed_claimed", -1))
        lease_conflicts = int(result.get("lease_conflicts", -1))
        child_counts = {
            str(disposition): int(count)
            for disposition, count in dict(result.get("outcome_counts") or {}).items()
        }
        child_outcomes = [dict(outcome) for outcome in list(result.get("outcomes") or [])]

        if found < 0 or claimed < 0 or lease_conflicts < 0 or found > remaining:
            raise RuntimeError("ARMED_REPLAY_CHILD_COUNT_INVALID")
        if found != claimed + lease_conflicts:
            raise RuntimeError("ARMED_REPLAY_CHILD_CLAIM_RECONCILIATION_FAILED")
        if sum(child_counts.values()) != claimed or len(child_outcomes) != claimed:
            raise RuntimeError("ARMED_REPLAY_CHILD_OUTCOME_RECONCILIATION_FAILED")

        total_found += found
        total_claimed += claimed
        total_lease_conflicts += lease_conflicts
        remaining -= found
        for disposition, count in child_counts.items():
            combined_counts[disposition] = combined_counts.get(disposition, 0) + count
        for outcome in child_outcomes:
            item = dict(outcome)
            item["paper_account_id"] = account_id
            combined_outcomes.append(item)
        account_results.append(
            {
                "paper_account_id": account_id,
                "armed_found": found,
                "armed_claimed": claimed,
                "lease_conflicts": lease_conflicts,
                "outcome_counts": child_counts,
            }
        )

    if total_found != total_claimed + total_lease_conflicts:
        raise RuntimeError("ARMED_REPLAY_TOTAL_CLAIM_RECONCILIATION_FAILED")
    if sum(combined_counts.values()) != total_claimed:
        raise RuntimeError("ARMED_REPLAY_TOTAL_OUTCOME_RECONCILIATION_FAILED")

    return {
        "ok": True,
        "operation": "REPLAY_ARMED_SIGNALS",
        "processed_at": now.isoformat(),
        "accounts_scanned": scanned,
        "account_results": account_results,
        "armed_found": total_found,
        "armed_claimed": total_claimed,
        "lease_conflicts": total_lease_conflicts,
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
            liquidity_store = _liquidity_store()
            ingress, sector_evidence = enrich_entry_sector(ingress, liquidity_store)
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
                liquidity_store,
            )
            execution = executor.execute(ingress, now=now)
            execution = attach_sector_evidence(execution, sector_evidence)
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
