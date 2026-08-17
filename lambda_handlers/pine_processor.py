"""AWS Lambda handler for fail-closed Pine and server-scanner paper processing."""

from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.dynamo_ledger import DynamoPaperLedger
from daily_alpha.execution_universe import build_scanner_ingress
from daily_alpha.pine_paper_orchestrator import AwsPinePaperExecutor, _all_open_trades
from daily_alpha.pine_processor import (
    DynamoPineEventStore,
    PineProcessorResult,
    process_sqs_batch,
)


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

    if operation == "EXECUTE_SCANNER_SIGNAL":
        now = datetime.now(UTC)
        try:
            raw_signal = event.get("signal")
            if not isinstance(raw_signal, dict):
                raise ValueError("SCANNER_SIGNAL_REQUIRED")
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
            executor = AwsPinePaperExecutor()
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

    store = DynamoPineEventStore()
    executor = AwsPinePaperExecutor()
    return process_sqs_batch(event, store, executor=executor)
