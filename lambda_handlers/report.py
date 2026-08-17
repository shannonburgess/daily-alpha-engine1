"""AWS Lambda entry point for Daily Alpha staging report generation."""

from __future__ import annotations

from typing import Any

from daily_alpha.staging_reporting import AwsStagingReportPublisher, StagingReportError


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Publish the latest research/newsletter/CSV bundle to staging S3."""
    base = {
        "service": "daily-alpha-report",
        "request_id": getattr(context, "aws_request_id", None),
        "live_trading_enabled": False,
    }
    if event.get("smoke_test") is True:
        return {"ok": True, "publish_enabled": True, **base}

    if str(event.get("operation", "")).strip().upper() != "PUBLISH_STAGING_REPORT":
        return {
            "ok": False,
            "publish_enabled": True,
            "status": "DATA_ERROR",
            "error_code": "UNSUPPORTED_OPERATION",
            **base,
        }

    try:
        result = AwsStagingReportPublisher().publish(
            session=str(event.get("session", "MANUAL")),
            run_id=str(event.get("run_id") or base["request_id"] or "lambda"),
        )
    except (StagingReportError, ValueError) as exc:
        return {
            "ok": False,
            "publish_enabled": True,
            "status": "DATA_ERROR",
            "error_code": str(exc) or type(exc).__name__,
            **base,
        }

    return {"publish_enabled": True, **base, **result}
