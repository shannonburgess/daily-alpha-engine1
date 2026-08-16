"""AWS Lambda entry point for the Daily Alpha staging paper trader."""

from __future__ import annotations

from typing import Any

from daily_alpha.dynamo_ledger import DynamoPaperLedger, LedgerStorageError
from daily_alpha.paper_runtime import PaperRuntimeError, process_paper_event
from daily_alpha.signals import SignalError
from daily_alpha.sizing import SizingError


def _build_ledger() -> DynamoPaperLedger:
    """Create the durable staging ledger only for real paper operations."""
    return DynamoPaperLedger()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Persist paper positions while keeping live brokerage execution impossible."""
    base = {
        "service": "daily-alpha-paper-trader",
        "paper_trading": True,
        "live_trading_enabled": False,
        "request_id": getattr(context, "aws_request_id", None),
        "event_received": bool(event),
    }

    if event.get("smoke_test") is True:
        return {"ok": True, **base}

    try:
        result = process_paper_event(event, _build_ledger())
    except LedgerStorageError as exc:
        return {
            "ok": False,
            **base,
            "status": "DATA_ERROR",
            "error_code": str(exc) or "PAPER_LEDGER_STORAGE_ERROR",
        }
    except (PaperRuntimeError, SignalError, SizingError, ValueError) as exc:
        return {
            "ok": False,
            **base,
            "status": "REJECTED",
            "error_code": str(exc) or type(exc).__name__,
        }

    return {
        "ok": True,
        **base,
        "workflow": "PAPER_LEDGER",
        **result,
    }
