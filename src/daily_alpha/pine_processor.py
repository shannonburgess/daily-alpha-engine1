"""Fail-closed processor boundary for normalized Pine ingress events.

The processor validates the execution-boundary contract, durably records each
received signal, and can hand the validated event to a paper-only executor. Live
brokerage execution is never authorized by this module.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .signals import PineSignal, SignalAction, SignalError, parse_pine_signal


class PineProcessorError(ValueError):
    """Raised when a queued Pine event cannot cross the processor boundary."""


@dataclass(frozen=True)
class PineProcessorResult:
    schema_version: str
    signal_id: str
    symbol: str
    action: str
    disposition: str
    reason: str
    received_at: str
    processed_at: str
    position_fraction: float | None = None
    runner_stage: str | None = None
    paper_ledger_updated: bool = False
    paper_execution_triggered: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CANONICAL_STRATEGY = "DA_TURTLE_ADAPTIVE_TREND"
CANONICAL_STRATEGY_VERSION = "2.3"
CANONICAL_TIMEFRAMES = {"D", "1D"}
CANONICAL_ADD_STAGES = {"ADD_1_ATR", "ADD_2_ATR"}
CANONICAL_PARTIAL_STAGE = "HARVEST_3_ATR"
CANONICAL_RUNNER_FRACTION = 0.25
INGRESS_SCHEMA_VERSIONS = {"2026-08-16-v2", "2026-08-16-v3"}
PROCESSOR_SCHEMA_VERSION = "2026-08-16-v2"


def process_ingress_record(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_queue_age_minutes: int = 30,
) -> PineProcessorResult:
    """Validate and classify one already-authenticated Pine ingress record."""
    if max_queue_age_minutes <= 0:
        raise PineProcessorError("max_queue_age_minutes must be positive")
    if not isinstance(payload, Mapping):
        raise PineProcessorError("PINE_PROCESSOR_RECORD_MUST_BE_OBJECT")
    if "webhook_secret" in payload:
        raise PineProcessorError("PINE_PROCESSOR_SECRET_MUST_NOT_BE_PRESENT")
    if str(payload.get("schema_version", "")) not in INGRESS_SCHEMA_VERSIONS:
        raise PineProcessorError("PINE_PROCESSOR_SCHEMA_UNSUPPORTED")
    if str(payload.get("source", "")) != "TRADINGVIEW_PINE":
        raise PineProcessorError("PINE_PROCESSOR_SOURCE_INVALID")

    for field in (
        "trading_authorized",
        "paper_execution_triggered",
        "live_trading_enabled",
    ):
        if payload.get(field) is not False:
            raise PineProcessorError(f"PINE_PROCESSOR_UNSAFE_FLAG_{field.upper()}")

    received_at = _timestamp(payload.get("received_at"), "received_at")
    processed_at = _aware(now or datetime.now(UTC))
    queue_age_minutes = (processed_at - received_at).total_seconds() / 60
    if queue_age_minutes < -1:
        raise PineProcessorError("PINE_PROCESSOR_RECEIVED_AT_IN_FUTURE")
    if queue_age_minutes > max_queue_age_minutes:
        raise PineProcessorError("PINE_PROCESSOR_QUEUE_EVENT_STALE")

    signal = _signal_from_ingress(payload, received_at)
    _validate_canonical_signal(signal)

    reason = _context_reason(signal.action)
    return PineProcessorResult(
        schema_version=PROCESSOR_SCHEMA_VERSION,
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        action=signal.action.value,
        disposition="HELD_FOR_CONTEXT",
        reason=reason,
        received_at=received_at.isoformat(),
        processed_at=processed_at.isoformat(),
        position_fraction=signal.position_fraction,
        runner_stage=signal.runner_stage,
    )


def process_sqs_batch(
    event: Mapping[str, Any],
    store: Any,
    *,
    executor: Any | None = None,
    now: datetime | None = None,
    max_queue_age_minutes: int = 30,
) -> dict[str, list[dict[str, str]]]:
    """Process an SQS batch with AWS partial-batch failure semantics."""
    records = event.get("Records", [])
    if not isinstance(records, list):
        raise PineProcessorError("SQS_RECORDS_MUST_BE_LIST")

    failures: list[dict[str, str]] = []
    for record in records:
        message_id = ""
        try:
            if not isinstance(record, Mapping):
                raise PineProcessorError("SQS_RECORD_MUST_BE_OBJECT")
            message_id = str(record.get("messageId", "")).strip()
            if not message_id:
                raise PineProcessorError("SQS_MESSAGE_ID_REQUIRED")
            body = _body(record.get("body"))
            result = process_ingress_record(
                body,
                now=now,
                max_queue_age_minutes=max_queue_age_minutes,
            )
            store.persist(body, result)
            if executor is not None:
                execution = executor.execute(body, now=now)
                store.mark_execution(result.signal_id, execution)
        except Exception:
            if message_id:
                failures.append({"itemIdentifier": message_id})
            else:
                raise
    return {"batchItemFailures": failures}


class DynamoPineEventStore:
    """Idempotent durable event/audit store for processor outcomes."""

    DEFAULT_TABLE_NAME = "daily-alpha-paper-ledger-staging"
    DEFAULT_ACCOUNT_ID = "paper-staging"

    def __init__(
        self,
        *,
        table_name: str | None = None,
        account_id: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.table_name = (
            table_name
            or os.getenv("DAILY_ALPHA_PAPER_LEDGER_TABLE")
            or self.DEFAULT_TABLE_NAME
        ).strip()
        self.account_id = (
            account_id
            or os.getenv("DAILY_ALPHA_PAPER_ACCOUNT_ID")
            or self.DEFAULT_ACCOUNT_ID
        ).strip()
        if not self.table_name or not self.account_id:
            raise PineProcessorError("PINE_PROCESSOR_STORE_CONFIGURATION_INVALID")
        if client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - Lambda includes boto3
                raise PineProcessorError("BOTO3_UNAVAILABLE") from exc
            client = boto3.client("dynamodb")
        self.client = client

    def persist(
        self,
        ingress: Mapping[str, Any],
        result: PineProcessorResult,
    ) -> bool:
        """Persist once by signal_id; return False for an already-stored duplicate."""
        item = {
            "pk": {
                "S": (
                    f"ACCOUNT#{self.account_id}#PINE_EVENT#"
                    f"{result.signal_id}"
                )
            },
            "sk": {"S": "RECEIVED"},
            "signal_id": {"S": result.signal_id},
            "symbol": {"S": result.symbol},
            "action": {"S": result.action},
            "disposition": {"S": result.disposition},
            "reason": {"S": result.reason},
            "ingress_json": {
                "S": json.dumps(dict(ingress), sort_keys=True, separators=(",", ":"))
            },
            "result_json": {
                "S": json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
            },
        }
        try:
            self.client.put_item(
                TableName=self.table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
        except Exception as exc:
            if _aws_error_code(exc) == "ConditionalCheckFailedException":
                return False
            raise PineProcessorError("PINE_PROCESSOR_DYNAMODB_WRITE_FAILED") from exc
        return True

    def mark_execution(
        self,
        signal_id: str,
        execution: Mapping[str, Any],
    ) -> None:
        """Attach the latest idempotent paper-execution outcome to the signal."""
        disposition = str(execution.get("disposition", "")).strip()
        reason = str(execution.get("reason", "")).strip()
        if not disposition or not reason:
            raise PineProcessorError("PINE_EXECUTION_OUTCOME_INVALID")
        try:
            self.client.update_item(
                TableName=self.table_name,
                Key={
                    "pk": {
                        "S": f"ACCOUNT#{self.account_id}#PINE_EVENT#{signal_id}"
                    },
                    "sk": {"S": "RECEIVED"},
                },
                UpdateExpression=(
                    "SET disposition = :disposition, reason = :reason, "
                    "execution_json = :execution"
                ),
                ExpressionAttributeValues={
                    ":disposition": {"S": disposition},
                    ":reason": {"S": reason},
                    ":execution": {
                        "S": json.dumps(
                            dict(execution), sort_keys=True, separators=(",", ":")
                        )
                    },
                },
                ConditionExpression="attribute_exists(pk)",
            )
        except Exception as exc:
            raise PineProcessorError("PINE_PROCESSOR_EXECUTION_WRITE_FAILED") from exc


def _signal_from_ingress(
    payload: Mapping[str, Any], received_at: datetime
) -> PineSignal:
    signal_payload = {
        "signal_id": payload.get("signal_id"),
        "symbol": payload.get("symbol"),
        "action": payload.get("action"),
        "strategy": payload.get("strategy"),
        "strategy_version": payload.get("strategy_version"),
        "timeframe": payload.get("timeframe"),
        "price": payload.get("price"),
        "bar_time": payload.get("bar_time"),
        "position_fraction": payload.get("position_fraction"),
        "runner_stage": payload.get("runner_stage"),
    }
    try:
        return parse_pine_signal(
            signal_payload,
            received_at=received_at,
            max_age_minutes=30,
        )
    except SignalError as exc:
        raise PineProcessorError(f"PINE_PROCESSOR_SIGNAL_INVALID:{exc}") from exc


def _validate_canonical_signal(signal: PineSignal) -> None:
    if signal.strategy != CANONICAL_STRATEGY:
        raise PineProcessorError("PINE_PROCESSOR_STRATEGY_NOT_CANONICAL")
    if signal.strategy_version != CANONICAL_STRATEGY_VERSION:
        raise PineProcessorError("PINE_PROCESSOR_STRATEGY_VERSION_NOT_CANONICAL")
    if signal.timeframe.upper() not in CANONICAL_TIMEFRAMES:
        raise PineProcessorError("PINE_PROCESSOR_TIMEFRAME_NOT_CANONICAL")

    if signal.action == SignalAction.ADD:
        if signal.runner_stage not in CANONICAL_ADD_STAGES:
            raise PineProcessorError("PINE_PROCESSOR_ADD_STAGE_INVALID")
        _require_runner_fraction(signal)
    elif signal.action == SignalAction.PARTIAL:
        if signal.runner_stage != CANONICAL_PARTIAL_STAGE:
            raise PineProcessorError("PINE_PROCESSOR_PARTIAL_STAGE_INVALID")
        _require_runner_fraction(signal)


def _require_runner_fraction(signal: PineSignal) -> None:
    value = signal.position_fraction
    if value is None or abs(value - CANONICAL_RUNNER_FRACTION) > 1e-9:
        raise PineProcessorError("PINE_PROCESSOR_RUNNER_FRACTION_INVALID")


def _context_reason(action: SignalAction) -> str:
    if action == SignalAction.ENTRY_LONG:
        return "ENTRY_REQUIRES_PORTFOLIO_RISK_ORATS_CONTEXT"
    if action == SignalAction.ADD:
        return "ADD_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_FILL_CONTEXT"
    if action == SignalAction.PARTIAL:
        return "PARTIAL_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_FILL_CONTEXT"
    return "EXIT_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_EXIT_PRICE_CONTEXT"


def _body(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        raise PineProcessorError("SQS_BODY_REQUIRED")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PineProcessorError("SQS_BODY_JSON_INVALID") from exc
    if not isinstance(decoded, dict):
        raise PineProcessorError("SQS_BODY_MUST_BE_OBJECT")
    return decoded


def _timestamp(value: Any, name: str) -> datetime:
    if not value:
        raise PineProcessorError(f"{name} is required")
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise PineProcessorError(f"{name} must be ISO-8601") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""
