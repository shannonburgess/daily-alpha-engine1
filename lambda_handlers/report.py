"""AWS Lambda entry point for Daily Alpha staging report generation."""

from __future__ import annotations

from typing import Any

from daily_alpha.newsletter import NewsletterRenderer


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return report-service readiness without publishing or emailing anything."""
    _ = NewsletterRenderer
    return {
        "ok": True,
        "service": "daily-alpha-report",
        "publish_enabled": False,
        "request_id": getattr(context, "aws_request_id", None),
        "event_received": bool(event),
    }
