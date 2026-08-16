"""AWS Lambda entry point for the Daily Alpha staging decision engine."""

from __future__ import annotations

from typing import Any

from daily_alpha.orchestrator import RunMode
from daily_alpha.runtime import RuntimeInputError, evaluate_entry_event
from daily_alpha.signals import SignalError


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run a real entry decision while remaining fail-closed and paper-only."""
    base = {
        "service": "daily-alpha-engine",
        "mode": RunMode.PAPER.value,
        "live_trading_enabled": False,
        "request_id": getattr(context, "aws_request_id", None),
        "event_received": bool(event),
    }

    if event.get("smoke_test") is True:
        return {"ok": True, **base}

    if str(event.get("operation", "")).upper() != "EVALUATE_ENTRY":
        return {
            "ok": False,
            **base,
            "status": "DATA_ERROR",
            "error_code": "UNSUPPORTED_OPERATION",
        }

    try:
        result = evaluate_entry_event(event)
    except (RuntimeInputError, SignalError, ValueError) as exc:
        return {
            "ok": False,
            **base,
            "status": "DATA_ERROR",
            "error_code": str(exc) or type(exc).__name__,
        }

    return {
        "ok": True,
        **base,
        "status": result["decision"]["status"],
        "workflow": "ENTRY_DECISION",
        **result,
    }
