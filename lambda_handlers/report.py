"""AWS Lambda entry point for Daily Alpha staging report generation and delivery."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from daily_alpha.newsletter_delivery import (
    AwsNewsletterEmailDelivery,
    NewsletterEmailDeliveryError,
)
from daily_alpha.prospect_staging_runtime import (
    AwsProspectStagingRuntimePublisher,
    PreparedProspectStagingRuntime,
    ProspectStagingRuntimeError,
)
from daily_alpha.staging_reporting import AwsStagingReportPublisher, StagingReportError

_PROSPECT_V1_RUNTIME_ENV = "DAILY_ALPHA_PROSPECT_V1_RUNTIME_ENABLED"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Publish the staging report and automatically email the complete newsletter."""
    prospect_runtime_enabled = _prospect_v1_runtime_enabled()
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
            "prospect_v1_launch_gate_supported": True,
            "prospect_v1_runtime_enabled": prospect_runtime_enabled,
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
            "prospect_v1_launch_gate_supported": True,
            "prospect_v1_runtime_enabled": prospect_runtime_enabled,
            "status": "DATA_ERROR",
            "error_code": "UNSUPPORTED_OPERATION",
            **base,
        }

    try:
        publisher = AwsStagingReportPublisher()
        result = publisher.publish(
            session=str(event.get("session", "MANUAL")),
            run_id=run_id,
        )
    except (StagingReportError, ValueError) as exc:
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "prospect_v1_launch_gate_supported": True,
            "prospect_v1_runtime_enabled": prospect_runtime_enabled,
            "status": "DATA_ERROR",
            "error_code": str(exc) or type(exc).__name__,
            **base,
        }

    prospect_runtime: AwsProspectStagingRuntimePublisher | None = None
    prepared: PreparedProspectStagingRuntime | None = None
    if prospect_runtime_enabled:
        try:
            prospect_runtime = AwsProspectStagingRuntimePublisher(
                s3_client=publisher.s3,
                bucket=publisher.bucket,
            )
            prepared = prospect_runtime.prepare(
                history_prefix=str(result.get("history_prefix") or ""),
                as_of=datetime.now(UTC),
            )
        except ProspectStagingRuntimeError as exc:
            return {
                "ok": False,
                "publish_enabled": True,
                "newsletter_email_supported": True,
                "prospect_v1_launch_gate_supported": True,
                "prospect_v1_runtime_enabled": True,
                "status": "PUBLISHED_PROSPECT_FAILED",
                "error_code": str(exc) or type(exc).__name__,
                "publication": result,
                "prospect_initial_rollout": {
                    "ready": False,
                    "reasons": [str(exc) or type(exc).__name__],
                    "trading_authorized": False,
                    "live_trading_enabled": False,
                },
                **base,
            }

    try:
        email_delivery = AwsNewsletterEmailDelivery().send_latest(
            report_date=str(result.get("report_date") or "LATEST"),
            session=str(result.get("session") or event.get("session") or "MANUAL"),
            run_id=run_id,
        )
    except NewsletterEmailDeliveryError as exc:
        prospect_status = (
            _finalize_prospect_safely(
                runtime=prospect_runtime,
                prepared=prepared,
                delivery_contract_validated=False,
            )
            if prospect_runtime is not None and prepared is not None
            else _disabled_prospect_status()
        )
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "prospect_v1_launch_gate_supported": True,
            "prospect_v1_runtime_enabled": prospect_runtime_enabled,
            "status": "PUBLISHED_EMAIL_FAILED",
            "error_code": exc.code,
            "publication": result,
            "prospect_initial_rollout": prospect_status,
            **base,
        }

    delivery_validated = email_delivery.get("status") == "SENT"
    if prospect_runtime is not None and prepared is not None:
        prospect_status = _finalize_prospect_safely(
            runtime=prospect_runtime,
            prepared=prepared,
            delivery_contract_validated=delivery_validated,
        )
        if delivery_validated and not prospect_status["ready"]:
            return {
                "ok": False,
                "publish_enabled": True,
                "newsletter_email_supported": True,
                "prospect_v1_launch_gate_supported": True,
                "prospect_v1_runtime_enabled": True,
                "status": "PUBLISHED_PROSPECT_GATE_FAILED",
                "error_code": "PROSPECT_INITIAL_ROLLOUT_GATE_NOT_READY",
                "publication": result,
                "email_delivery": email_delivery,
                "prospect_initial_rollout": prospect_status,
                **base,
            }
    else:
        prospect_status = _disabled_prospect_status()

    return {
        "publish_enabled": True,
        "newsletter_email_supported": True,
        "prospect_v1_launch_gate_supported": True,
        "prospect_v1_runtime_enabled": prospect_runtime_enabled,
        **base,
        **result,
        "email_delivery": email_delivery,
        "prospect_initial_rollout": prospect_status,
    }


def _prospect_v1_runtime_enabled() -> bool:
    return os.getenv(_PROSPECT_V1_RUNTIME_ENV, "").strip().lower() in _TRUE_VALUES


def _disabled_prospect_status() -> dict[str, object]:
    return {
        "ready": False,
        "delivery_contract_validated": False,
        "reasons": ["PROSPECT_V1_RUNTIME_DISABLED"],
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _finalize_prospect_safely(
    *,
    runtime: AwsProspectStagingRuntimePublisher,
    prepared: PreparedProspectStagingRuntime,
    delivery_contract_validated: bool,
) -> dict[str, object]:
    summary = prepared.summary()
    try:
        gate = runtime.finalize_delivery(
            prepared,
            delivery_contract_validated=delivery_contract_validated,
        )
    except ProspectStagingRuntimeError as exc:
        return {
            **summary,
            "ready": False,
            "delivery_contract_validated": delivery_contract_validated,
            "reasons": [f"PROSPECT_LAUNCH_GATE_PERSIST_FAILED:{exc}"],
            "trading_authorized": False,
            "live_trading_enabled": False,
        }
    return {
        **summary,
        "ready": gate.ready,
        "delivery_contract_validated": gate.delivery_contract_validated,
        "reasons": list(gate.reasons),
        "trading_authorized": False,
        "live_trading_enabled": False,
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
            "prospect_v1_launch_gate_supported": True,
            "status": "EMAIL_FAILED",
            "error_code": exc.code,
            **base,
        }

    if email_delivery.get("status") != "SENT":
        return {
            "ok": False,
            "publish_enabled": True,
            "newsletter_email_supported": True,
            "prospect_v1_launch_gate_supported": True,
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
        "prospect_v1_launch_gate_supported": True,
        "status": "EMAIL_SENT",
        "email_delivery": email_delivery,
        **base,
    }
