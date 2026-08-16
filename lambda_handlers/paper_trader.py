"""AWS Lambda entry point for the Daily Alpha staging paper trader."""

from __future__ import annotations

from typing import Any

from daily_alpha.execution import FillStatus


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return paper-trader readiness; this boundary never enables live execution."""
    _ = FillStatus
    return {
        "ok": True,
        "service": "daily-alpha-paper-trader",
        "paper_trading": True,
        "live_trading_enabled": False,
        "request_id": getattr(context, "aws_request_id", None),
        "event_received": bool(event),
    }
