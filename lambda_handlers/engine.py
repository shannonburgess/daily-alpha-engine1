"""AWS Lambda entry point for the Daily Alpha staging engine.

This boundary is intentionally fail-closed and does not enable live brokerage execution.
"""

from __future__ import annotations

from typing import Any

from daily_alpha.orchestrator import RunMode


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return a safe staging readiness response for the engine service."""
    return {
        "ok": True,
        "service": "daily-alpha-engine",
        "mode": RunMode.PAPER.value,
        "live_trading_enabled": False,
        "request_id": getattr(context, "aws_request_id", None),
        "event_received": bool(event),
    }
