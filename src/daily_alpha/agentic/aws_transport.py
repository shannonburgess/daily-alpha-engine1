"""Repo-only AWS connector/transport contracts for institutional data ingestion.

This layer models EventBridge, Step Functions, SQS/DLQ, Secrets Manager references,
immutable S3 raw-response retention, retries, throttling, source health, and deterministic
handoff into source adapters. It does not import boto3, deploy AWS resources, expose
secret values, authorize trading, or connect to a broker.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .durable_evidence import SourceHealthStatus
from .public_primary_adapters import (
    FredAlfredAdapter,
    HttpRequestSpec,
    OpenFigiAdapter,
    SecEdgarAdapter,
)


class AwsTransportError(ValueError):
    """AWS transport contract or deterministic handoff invariant failed."""


class TransportMode(StrEnum):
    SCHEDULED_PULL = "SCHEDULED_PULL"
    EVENT_WEBHOOK = "EVENT_WEBHOOK"
    STREAMING = "STREAMING"


class RetryDisposition(StrEnum):
    SUCCESS = "SUCCESS"
    RETRYABLE = "RETRYABLE"
    RATE_LIMITED = "RATE_LIMITED"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


class PublicAdapterRoute(StrEnum):
    OPENFIGI_MAPPING = "OPENFIGI_MAPPING"
    SEC_SUBMISSIONS = "SEC_SUBMISSIONS"
    FRED_OBSERVATIONS = "FRED_OBSERVATIONS"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AwsTransportError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AwsTransportError("TRANSPORT_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_pairs(
    values: tuple[tuple[str, str], ...] | dict[str, str],
) -> tuple[tuple[str, str], ...]:
    items = values.items() if isinstance(values, dict) else values
    normalized = tuple(sorted((str(key).strip().lower(), str(value).strip()) for key, value in items))
    if any(not key for key, _ in normalized):
        raise AwsTransportError("TRANSPORT_HEADER_OR_PARAMETER_KEY_REQUIRED")
    if len({key for key, _ in normalized}) != len(normalized):
        raise AwsTransportError("TRANSPORT_HEADER_OR_PARAMETER_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True)
class SecretReference:
    """Logical Secrets Manager reference. Secret material is never stored here."""

    secret_name: str
    version_stage: str = "AWSCURRENT"

    def __post_init__(self) -> None:
        name = self.secret_name.strip()
        stage = self.version_stage.strip().upper()
        if not name or not stage:
            raise AwsTransportError("SECRET_REFERENCE_FIELDS_REQUIRED")
        object.__setattr__(self, "secret_name", name)
        object.__setattr__(self, "version_stage", stage)

    @property
    def reference_id(self) -> str:
        return _digest({"secret_name": self.secret_name, "version_stage": self.version_stage})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise AwsTransportError("RETRY_MAX_ATTEMPTS_MUST_BE_POSITIVE")
        numeric = (self.base_delay_seconds, self.max_delay_seconds, self.multiplier)
        if any(not math.isfinite(value) or value <= 0 for value in numeric):
            raise AwsTransportError("RETRY_POLICY_VALUES_MUST_BE_POSITIVE")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise AwsTransportError("RETRY_MAX_DELAY_BELOW_BASE_DELAY")
        if self.multiplier < 1.0:
            raise AwsTransportError("RETRY_MULTIPLIER_BELOW_ONE")

    def delay_seconds(self, attempt: int, retry_after_seconds: float | None = None) -> float:
        if attempt <= 0:
            raise AwsTransportError("RETRY_ATTEMPT_MUST_BE_POSITIVE")
        if retry_after_seconds is not None:
            if not math.isfinite(retry_after_seconds) or retry_after_seconds < 0:
                raise AwsTransportError("RETRY_AFTER_INVALID")
            return min(self.max_delay_seconds, retry_after_seconds)
        delay = self.base_delay_seconds * (self.multiplier ** (attempt - 1))
        return min(self.max_delay_seconds, delay)

    def can_retry(self, attempt: int) -> bool:
        return 0 < attempt < self.max_attempts


@dataclass(frozen=True)
class RateLimitPolicy:
    provider_id: str
    requests_per_second: float
    burst_capacity: int
    daily_quota: int | None = None

    def __post_init__(self) -> None:
        provider = self.provider_id.strip().upper()
        if not provider:
            raise AwsTransportError("RATE_LIMIT_PROVIDER_REQUIRED")
        if not math.isfinite(self.requests_per_second) or self.requests_per_second <= 0:
            raise AwsTransportError("RATE_LIMIT_RPS_MUST_BE_POSITIVE")
        if self.burst_capacity <= 0:
            raise AwsTransportError("RATE_LIMIT_BURST_MUST_BE_POSITIVE")
        if self.daily_quota is not None and self.daily_quota <= 0:
            raise AwsTransportError("RATE_LIMIT_DAILY_QUOTA_MUST_BE_POSITIVE")
        object.__setattr__(self, "provider_id", provider)

    @property
    def policy_id(self) -> str:
        return _digest(self.__dict__)


@dataclass(frozen=True)
class EventBridgeTriggerMetadata:
    rule_name: str
    event_id: str
    triggered_at: datetime
    detail_type: str

    def __post_init__(self) -> None:
        rule = self.rule_name.strip()
        event = self.event_id.strip()
        detail = self.detail_type.strip()
        if not rule or not event or not detail:
            raise AwsTransportError("EVENTBRIDGE_TRIGGER_FIELDS_REQUIRED")
        object.__setattr__(self, "rule_name", rule)
        object.__setattr__(self, "event_id", event)
        object.__setattr__(self, "detail_type", detail)
        object.__setattr__(self, "triggered_at", _aware_utc(self.triggered_at, "EVENTBRIDGE_TRIGGERED_AT"))

    @property
    def trigger_id(self) -> str:
        return _digest(
            {
                "rule_name": self.rule_name,
                "event_id": self.event_id,
                "triggered_at": self.triggered_at.isoformat(),
                "detail_type": self.detail_type,
            }
        )


@dataclass(frozen=True)
class StepFunctionsExecutionMetadata:
    state_machine_name: str
    execution_name: str
    started_at: datetime

    def __post_init__(self) -> None:
        state_machine = self.state_machine_name.strip()
        execution = self.execution_name.strip()
        if not state_machine or not execution:
            raise AwsTransportError("STEP_FUNCTIONS_EXECUTION_FIELDS_REQUIRED")
        object.__setattr__(self, "state_machine_name", state_machine)
        object.__setattr__(self, "execution_name", execution)
        object.__setattr__(self, "started_at", _aware_utc(self.started_at, "STEP_FUNCTIONS_STARTED_AT"))

    @property
    def execution_id(self) -> str:
        return _digest(
            {
                "state_machine_name": self.state_machine_name,
                "execution_name": self.execution_name,
                "started_at": self.started_at.isoformat(),
            }
        )


@dataclass(frozen=True)
class TransportRequestEnvelope:
    provider_id: str
    mode: TransportMode
    request_spec: HttpRequestSpec
    created_at: datetime
    trigger_id: str
    attempt: int = 1
    secret_reference: SecretReference | None = None
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        provider = self.provider_id.strip().upper()
        trigger = self.trigger_id.strip().lower()
        if not provider or not trigger:
            raise AwsTransportError("TRANSPORT_REQUEST_IDENTITY_REQUIRED")
        if self.attempt <= 0:
            raise AwsTransportError("TRANSPORT_REQUEST_ATTEMPT_MUST_BE_POSITIVE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise AwsTransportError("TRANSPORT_REQUEST_MUST_REMAIN_RESEARCH_ONLY")
        if self.request_spec.requires_secret:
            if self.secret_reference is None:
                raise AwsTransportError("TRANSPORT_REQUEST_SECRET_REFERENCE_REQUIRED")
            if self.request_spec.secret_name != self.secret_reference.secret_name:
                raise AwsTransportError("TRANSPORT_REQUEST_SECRET_REFERENCE_MISMATCH")
        elif self.secret_reference is not None:
            raise AwsTransportError("TRANSPORT_REQUEST_UNNEEDED_SECRET_REFERENCE")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "trigger_id", trigger)
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "TRANSPORT_REQUEST_CREATED_AT"))

    @property
    def idempotency_key(self) -> str:
        return _digest(
            {
                "provider_id": self.provider_id,
                "request_id": self.request_spec.request_id,
                "trigger_id": self.trigger_id,
            }
        )

    @property
    def envelope_id(self) -> str:
        return _digest(
            {
                "provider_id": self.provider_id,
                "mode": self.mode.value,
                "request_id": self.request_spec.request_id,
                "created_at": self.created_at.isoformat(),
                "trigger_id": self.trigger_id,
                "attempt": self.attempt,
                "idempotency_key": self.idempotency_key,
                "secret_reference_id": (
                    self.secret_reference.reference_id if self.secret_reference else None
                ),
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class TransportResponseReceipt:
    envelope_id: str
    idempotency_key: str
    provider_id: str
    request_id: str
    received_at: datetime
    status_code: int
    latency_ms: float
    body_sha256: str
    content_length: int
    disposition: RetryDisposition
    headers: tuple[tuple[str, str], ...] | dict[str, str] = field(default_factory=tuple)
    retry_after_seconds: float | None = None
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        provider = self.provider_id.strip().upper()
        if not all((self.envelope_id.strip(), self.idempotency_key.strip(), self.request_id.strip(), provider)):
            raise AwsTransportError("TRANSPORT_RECEIPT_IDENTITY_REQUIRED")
        if not 100 <= self.status_code <= 599:
            raise AwsTransportError("TRANSPORT_STATUS_CODE_INVALID")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise AwsTransportError("TRANSPORT_LATENCY_INVALID")
        if self.content_length < 0 or not self.body_sha256.strip():
            raise AwsTransportError("TRANSPORT_BODY_METADATA_INVALID")
        if self.retry_after_seconds is not None and (
            not math.isfinite(self.retry_after_seconds) or self.retry_after_seconds < 0
        ):
            raise AwsTransportError("TRANSPORT_RETRY_AFTER_INVALID")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise AwsTransportError("TRANSPORT_RECEIPT_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "received_at", _aware_utc(self.received_at, "TRANSPORT_RECEIVED_AT"))
        object.__setattr__(self, "headers", _normalize_pairs(self.headers))

    @classmethod
    def from_http_response(
        cls,
        *,
        envelope: TransportRequestEnvelope,
        body: bytes,
        received_at: datetime,
        status_code: int,
        latency_ms: float,
        headers: tuple[tuple[str, str], ...] | dict[str, str] = (),
        retry_after_seconds: float | None = None,
    ) -> TransportResponseReceipt:
        return cls(
            envelope_id=envelope.envelope_id,
            idempotency_key=envelope.idempotency_key,
            provider_id=envelope.provider_id,
            request_id=envelope.request_spec.request_id,
            received_at=received_at,
            status_code=status_code,
            latency_ms=latency_ms,
            body_sha256=hashlib.sha256(body).hexdigest(),
            content_length=len(body),
            disposition=classify_http_status(status_code),
            headers=headers,
            retry_after_seconds=retry_after_seconds,
        )

    @property
    def receipt_id(self) -> str:
        return _digest(
            {
                "envelope_id": self.envelope_id,
                "idempotency_key": self.idempotency_key,
                "provider_id": self.provider_id,
                "request_id": self.request_id,
                "received_at": self.received_at.isoformat(),
                "status_code": self.status_code,
                "latency_ms": self.latency_ms,
                "body_sha256": self.body_sha256,
                "content_length": self.content_length,
                "disposition": self.disposition.value,
                "headers": list(self.headers),
                "retry_after_seconds": self.retry_after_seconds,
            }
        )

    def validate_body(self, body: bytes) -> None:
        if len(body) != self.content_length or hashlib.sha256(body).hexdigest() != self.body_sha256:
            raise AwsTransportError("TRANSPORT_BODY_CHECKSUM_MISMATCH")

    def validate_point_in_time(self, as_of: datetime, max_age_seconds: int) -> None:
        boundary = _aware_utc(as_of, "TRANSPORT_AS_OF")
        if max_age_seconds <= 0:
            raise AwsTransportError("TRANSPORT_MAX_AGE_MUST_BE_POSITIVE")
        if self.received_at > boundary:
            raise AwsTransportError("FUTURE_TRANSPORT_RECEIPT_NOT_ALLOWED")
        if (boundary - self.received_at).total_seconds() > max_age_seconds:
            raise AwsTransportError("TRANSPORT_RECEIPT_STALE")


@dataclass(frozen=True)
class RawArchivePointer:
    bucket_name: str
    object_key: str
    body_sha256: str
    content_length: int
    archived_at: datetime
    kms_key_alias: str | None = None

    def __post_init__(self) -> None:
        bucket = self.bucket_name.strip()
        key = self.object_key.strip().lstrip("/")
        if not bucket or not key or not self.body_sha256.strip() or self.content_length < 0:
            raise AwsTransportError("RAW_ARCHIVE_POINTER_FIELDS_INVALID")
        object.__setattr__(self, "bucket_name", bucket)
        object.__setattr__(self, "object_key", key)
        object.__setattr__(self, "archived_at", _aware_utc(self.archived_at, "RAW_ARCHIVED_AT"))
        if self.kms_key_alias is not None:
            object.__setattr__(self, "kms_key_alias", self.kms_key_alias.strip() or None)

    @classmethod
    def for_receipt(
        cls,
        *,
        bucket_name: str,
        receipt: TransportResponseReceipt,
        archived_at: datetime,
        kms_key_alias: str | None = None,
    ) -> RawArchivePointer:
        timestamp = receipt.received_at
        key = (
            f"raw/{receipt.provider_id.lower()}/{timestamp:%Y/%m/%d}/"
            f"{receipt.request_id}/{receipt.receipt_id}.json"
        )
        return cls(
            bucket_name=bucket_name,
            object_key=key,
            body_sha256=receipt.body_sha256,
            content_length=receipt.content_length,
            archived_at=archived_at,
            kms_key_alias=kms_key_alias,
        )

    @property
    def archive_id(self) -> str:
        return _digest(
            {
                "bucket_name": self.bucket_name,
                "object_key": self.object_key,
                "body_sha256": self.body_sha256,
                "content_length": self.content_length,
                "archived_at": self.archived_at.isoformat(),
                "kms_key_alias": self.kms_key_alias,
            }
        )


@dataclass(frozen=True)
class QueueDeliveryEnvelope:
    receipt_id: str
    idempotency_key: str
    delivery_id: str
    first_seen_at: datetime
    delivered_at: datetime
    replay_count: int = 0
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not all((self.receipt_id.strip(), self.idempotency_key.strip(), self.delivery_id.strip())):
            raise AwsTransportError("QUEUE_DELIVERY_IDENTITY_REQUIRED")
        if self.replay_count < 0:
            raise AwsTransportError("QUEUE_REPLAY_COUNT_INVALID")
        first_seen = _aware_utc(self.first_seen_at, "QUEUE_FIRST_SEEN_AT")
        delivered = _aware_utc(self.delivered_at, "QUEUE_DELIVERED_AT")
        if delivered < first_seen:
            raise AwsTransportError("QUEUE_DELIVERED_BEFORE_FIRST_SEEN")
        object.__setattr__(self, "first_seen_at", first_seen)
        object.__setattr__(self, "delivered_at", delivered)
        if self.failure_code is not None:
            object.__setattr__(self, "failure_code", self.failure_code.strip().upper() or None)

    def should_send_to_dlq(self, max_replays: int) -> bool:
        if max_replays < 0:
            raise AwsTransportError("QUEUE_MAX_REPLAYS_INVALID")
        return self.replay_count > max_replays


class InMemoryIdempotencyLedger:
    """Reference implementation for DynamoDB conditional-put semantics."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, idempotency_key: str) -> bool:
        key = idempotency_key.strip().lower()
        if not key:
            raise AwsTransportError("IDEMPOTENCY_KEY_REQUIRED")
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True


@dataclass(frozen=True)
class SourceTransportTelemetry:
    provider_id: str
    observed_at: datetime
    status: SourceHealthStatus
    latency_ms: float | None
    freshness_seconds: float | None
    last_success_at: datetime | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        provider = self.provider_id.strip().upper()
        if not provider:
            raise AwsTransportError("TRANSPORT_TELEMETRY_PROVIDER_REQUIRED")
        if self.latency_ms is not None and (
            not math.isfinite(self.latency_ms) or self.latency_ms < 0
        ):
            raise AwsTransportError("TRANSPORT_TELEMETRY_LATENCY_INVALID")
        if self.freshness_seconds is not None and (
            not math.isfinite(self.freshness_seconds) or self.freshness_seconds < 0
        ):
            raise AwsTransportError("TRANSPORT_TELEMETRY_FRESHNESS_INVALID")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "TRANSPORT_TELEMETRY_OBSERVED_AT"))
        if self.last_success_at is not None:
            object.__setattr__(
                self,
                "last_success_at",
                _aware_utc(self.last_success_at, "TRANSPORT_TELEMETRY_LAST_SUCCESS_AT"),
            )
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", self.reason_code.strip().upper() or None)

    @property
    def telemetry_id(self) -> str:
        return _digest(
            {
                "provider_id": self.provider_id,
                "observed_at": self.observed_at.isoformat(),
                "status": self.status.value,
                "latency_ms": self.latency_ms,
                "freshness_seconds": self.freshness_seconds,
                "last_success_at": (
                    self.last_success_at.isoformat() if self.last_success_at else None
                ),
                "reason_code": self.reason_code,
            }
        )


@dataclass(frozen=True)
class AdapterHandoffResult:
    route: PublicAdapterRoute
    receipt_id: str
    record_ids: tuple[str, ...]
    records: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not self.receipt_id.strip():
            raise AwsTransportError("ADAPTER_HANDOFF_RECEIPT_ID_REQUIRED")
        if len(self.record_ids) != len(self.records):
            raise AwsTransportError("ADAPTER_HANDOFF_RECORD_ID_LENGTH_MISMATCH")
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(self, "records", tuple(self.records))

    @property
    def handoff_id(self) -> str:
        return _digest(
            {
                "route": self.route.value,
                "receipt_id": self.receipt_id,
                "record_ids": list(self.record_ids),
            }
        )


class PublicPrimaryTransportRouter:
    """Verify archived transport bytes before invoking deterministic Stage 9A adapters."""

    @staticmethod
    def handoff(
        *,
        route: PublicAdapterRoute,
        receipt: TransportResponseReceipt,
        body: bytes,
        parameters: tuple[tuple[str, str], ...] | dict[str, str] = (),
    ) -> AdapterHandoffResult:
        if receipt.disposition is not RetryDisposition.SUCCESS:
            raise AwsTransportError("NON_SUCCESS_RECEIPT_CANNOT_HANDOFF")
        receipt.validate_body(body)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AwsTransportError("TRANSPORT_JSON_PAYLOAD_INVALID") from exc
        params = dict(_normalize_pairs(parameters))

        if route is PublicAdapterRoute.OPENFIGI_MAPPING:
            records = OpenFigiAdapter.parse_mapping_response(payload)
            record_ids = tuple(item.mapping_id for item in records)
        elif route is PublicAdapterRoute.SEC_SUBMISSIONS:
            records = SecEdgarAdapter.parse_recent_filings(payload)
            record_ids = tuple(item.filing_id for item in records)
        elif route is PublicAdapterRoute.FRED_OBSERVATIONS:
            series_id = params.get("series_id", "").strip().upper()
            if not series_id:
                raise AwsTransportError("FRED_HANDOFF_SERIES_ID_REQUIRED")
            records = FredAlfredAdapter.parse_observations(payload, series_id=series_id)
            record_ids = tuple(item.vintage_id for item in records)
        else:
            raise AwsTransportError("PUBLIC_ADAPTER_ROUTE_UNSUPPORTED")

        return AdapterHandoffResult(
            route=route,
            receipt_id=receipt.receipt_id,
            record_ids=record_ids,
            records=records,
        )


def classify_http_status(status_code: int) -> RetryDisposition:
    if not 100 <= status_code <= 599:
        raise AwsTransportError("TRANSPORT_STATUS_CODE_INVALID")
    if 200 <= status_code <= 299:
        return RetryDisposition.SUCCESS
    if status_code == 429:
        return RetryDisposition.RATE_LIMITED
    if status_code in {408, 425} or 500 <= status_code <= 599:
        return RetryDisposition.RETRYABLE
    return RetryDisposition.PERMANENT_FAILURE


def classify_transport_error(error_code: str) -> RetryDisposition:
    code = error_code.strip().upper()
    if not code:
        raise AwsTransportError("TRANSPORT_ERROR_CODE_REQUIRED")
    if code in {"TIMEOUT", "CONNECTION_RESET", "DNS_TEMPORARY", "TLS_HANDSHAKE_TEMPORARY"}:
        return RetryDisposition.RETRYABLE
    if code in {"RATE_LIMIT", "QUOTA_TEMPORARY"}:
        return RetryDisposition.RATE_LIMITED
    return RetryDisposition.PERMANENT_FAILURE
