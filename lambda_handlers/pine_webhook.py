"""AWS Lambda entry point for authenticated TradingView/Pine webhook ingress."""

from __future__ import annotations

import json
import os
from typing import Any

from daily_alpha.pine_ingress import (
    PineIngressAuthError,
    PineIngressError,
    build_pine_ingress_record,
)
from daily_alpha.signals import SignalError


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validate a Pine alert and enqueue it; never evaluate or execute a trade."""
    expected_secret = os.environ.get("PINE_WEBHOOK_SECRET", "")
    queue_url = os.environ.get("PINE_INGRESS_QUEUE_URL", "")
    request_id = getattr(context, "aws_request_id", None)

    if not expected_secret:
        return _response(503, "INGRESS_NOT_CONFIGURED", request_id=request_id)

    try:
        record = build_pine_ingress_record(event, expected_secret=expected_secret)
    except PineIngressAuthError:
        return _response(401, "UNAUTHORIZED", request_id=request_id)
    except (PineIngressError, SignalError, ValueError) as exc:
        return _response(
            400,
            "INVALID_SIGNAL",
            error_code=str(exc) or type(exc).__name__,
            request_id=request_id,
        )

    if not queue_url:
        return _response(
            503,
            "INGRESS_QUEUE_NOT_CONFIGURED",
            signal_id=record.signal_id,
            request_id=request_id,
        )

    try:
        import boto3

        boto3.client("sqs").send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(record.to_dict(), separators=(",", ":"), sort_keys=True),
        )
    except Exception:  # noqa: BLE001 - public ingress must fail closed on any queue failure
        # Do not echo provider errors or request contents to the public webhook caller.
        return _response(
            503,
            "INGRESS_QUEUE_ERROR",
            signal_id=record.signal_id,
            request_id=request_id,
        )

    return _response(
        202,
        "ACCEPTED",
        signal_id=record.signal_id,
        symbol=record.symbol,
        action=record.action,
        request_id=request_id,
    )


def _response(status_code: int, status: str, **fields: Any) -> dict[str, Any]:
    payload = {
        "ok": 200 <= status_code < 300,
        "status": status,
        "paper_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
        **{key: value for key, value in fields.items() if value is not None},
    }
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }
