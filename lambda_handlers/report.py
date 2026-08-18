"""AWS Lambda entry point for Daily Alpha staging report generation and delivery."""

from __future__ import annotations

from typing import Any

from daily_alpha.newsletter_delivery import (
    AwsNewsletterEmailDelivery,
    NewsletterEmailDeliveryError,
)
from daily_alpha.staging_reporting import AwsStagingReportPublisher, StagingReportError


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Publish the staging report and automatically email the complete newsletter."""
    base = {
        "service": "daily-alpha-report",
        "request_id": getattr(context, "aws_request_id", None),
        "live_trading_enabled": False,
    }
    if event.get("smoke_test") is True:
        return {
            "ok": True,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            **base,
        }

    operation = str(event.get("operation", "")).strip().upper()
    run_id = str(event.get("run_id") or base["request_id"] or "lambda")

    if operation == "SEND_LATEST_NEWSLETTER":
        return _send_latest(event=event, run_id=run_id, base=base)

    if operation != "PUBLISH_STAGING_REPORT":
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "status": "DATA_ERROR",
            "error_code": "UNSUPPORTED_OPERATION",
            **base,
        }

    try:
        result = AwsStagingReportPublisher().publish(
            session=str(event.get("session", "MANUAL")),
            run_id=run_id,
        )
    except (StagingReportError, ValueError) as exc:
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "status": "DATA_ERROR",
            "error_code": str(exc) or type(exc).__name__,
            **base,
        }

    try:
        email_delivery = AwsNewsletterEmailDelivery().send_latest(
            report_date=str(result.get("report_date") or "LATEST"),
            session=str(result.get("session") or event.get("session") or "MANUAL"),
            run_id=run_id,
        )
    except NewsletterEmailDeliveryError as exc:
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "status": "PUBLISHED_EMAIL_FAILED",
            "error_code": exc.code,
            "publication": result,
            **base,
        }

    return {
        "publish_enabled": True,
        "newsletter_email_supported": True,
        **base,
        **result,
        "email_delivery": email_delivery,
    }


def _send_latest(
    *,
    event: dict[str, Any],
    run_id: str,
    base: dict[str, Any],
) -> dict[str, Any]:
    """Resend the latest S3 newsletter without rebuilding research inputs."""
    try:
        email_delivery = AwsNewsletterEmailDelivery().send_latest(
            report_date=str(event.get("report_date") or "LATEST"),
            session=str(event.get("session") or "MANUAL"),
            run_id=run_id,
        )
    except NewsletterEmailDeliveryError as exc:
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "status": "EMAIL_FAILED",
            "error_code": exc.code,
            **base,
        }

    if email_delivery.get("status") != "SENT":
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "status": "EMAIL_DISABLED",
            "error_code": str(
                email_delivery.get("reason") or "NEWSLETTER_EMAIL_CONFIG_NOT_SET"
            ),
            "email_delivery": email_delivery,
            **base,
        }

    return {
        "ok": True,
        "publish_enabled": True,
        "newsletter_email_supported": True,
        "status": "EMAIL_SENT",
        "email_delivery": email_delivery,
        **base,
    }
