"""Bind immutable staging feed receipts to point-in-time model features.

This module does not parse provider payloads into features and does not create labels.
Callers must supply explicit scalar feature facts. The adapter only proves that those
facts are bound to exact immutable raw bytes and that their model ``known_at`` time is
the trusted capture time recorded by the staging ingestion receipt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any

from .model_dataset_builder import PointInTimeFeatureObservation
from .model_training import ModelTrainingError

_RECEIPT_SCHEMA = "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1"
_ALLOWED_PROVIDERS = frozenset({"MASSIVE", "TIINGO", "FRED"})
_CAPTURE_MODE_CURRENT = "CURRENT_WINDOW"
_CAPTURE_MODE_HISTORICAL = "HISTORICAL_BACKFILL"
_CAPTURE_MODES = frozenset({_CAPTURE_MODE_CURRENT, _CAPTURE_MODE_HISTORICAL})
_KNOWN_AT_BASIS = "CAPTURED_AT_ONLY"
_MAX_HISTORICAL_BACKFILL_DAYS = 31
_SOURCE_REVISION_PREFIX = "feed-receipt-pit-v2"


@dataclass(frozen=True, slots=True)
class ImmutableFeedEvidence:
    """Validated identity for one immutable raw provider response and receipt."""

    provider: str
    target: str
    captured_at: datetime
    capture_mode: str
    requested_start_date: date
    requested_end_date: date
    known_at_basis: str
    historical_known_at_backdating_authorized: bool
    raw_s3_key: str
    raw_sha256: str
    raw_bytes: int
    evidence_id: str
    source_revision: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        provider = self.provider.strip().upper()
        target = self.target.strip().upper()
        capture_mode = self.capture_mode.strip().upper()
        known_at_basis = self.known_at_basis.strip().upper()
        raw_s3_key = self.raw_s3_key.strip()
        raw_sha256 = self.raw_sha256.strip().lower()
        evidence_id = self.evidence_id.strip().lower()
        source_revision = self.source_revision.strip()

        if provider not in _ALLOWED_PROVIDERS:
            raise ModelTrainingError("FEED_EVIDENCE_PROVIDER_INVALID")
        if not target:
            raise ModelTrainingError("FEED_EVIDENCE_TARGET_REQUIRED")
        _require_aware(self.captured_at, "FEED_EVIDENCE_CAPTURED_AT")
        _validate_capture_lineage(
            capture_mode=capture_mode,
            requested_start_date=self.requested_start_date,
            requested_end_date=self.requested_end_date,
            captured_at=self.captured_at,
            known_at_basis=known_at_basis,
            historical_known_at_backdating_authorized=(
                self.historical_known_at_backdating_authorized
            ),
            prefix="FEED_EVIDENCE",
        )
        _require_raw_key(provider=provider, target=target, raw_s3_key=raw_s3_key)
        _require_sha256(raw_sha256, "FEED_EVIDENCE_RAW_SHA256")
        if isinstance(self.raw_bytes, bool) or not isinstance(self.raw_bytes, int):
            raise ModelTrainingError("FEED_EVIDENCE_RAW_BYTES_INVALID")
        if self.raw_bytes < 1:
            raise ModelTrainingError("FEED_EVIDENCE_RAW_BYTES_INVALID")
        _require_sha256(evidence_id, "FEED_EVIDENCE_ID")

        expected_evidence_id = _sha(
            _evidence_identity_payload(
                provider=provider,
                target=target,
                captured_at=self.captured_at,
                capture_mode=capture_mode,
                requested_start_date=self.requested_start_date,
                requested_end_date=self.requested_end_date,
                known_at_basis=known_at_basis,
                historical_known_at_backdating_authorized=(
                    self.historical_known_at_backdating_authorized
                ),
                raw_s3_key=raw_s3_key,
                raw_sha256=raw_sha256,
                raw_bytes=self.raw_bytes,
            )
        )
        if evidence_id != expected_evidence_id:
            raise ModelTrainingError("FEED_EVIDENCE_ID_MISMATCH")
        if source_revision != f"{_SOURCE_REVISION_PREFIX}:{evidence_id}":
            raise ModelTrainingError("FEED_EVIDENCE_SOURCE_REVISION_MISMATCH")
        if not self.research_only:
            raise ModelTrainingError("FEED_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        if self.trading_authorized or self.live_trading_enabled:
            raise ModelTrainingError("FEED_EVIDENCE_CANNOT_AUTHORIZE_TRADING")

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "capture_mode", capture_mode)
        object.__setattr__(self, "known_at_basis", known_at_basis)
        object.__setattr__(self, "raw_s3_key", raw_s3_key)
        object.__setattr__(self, "raw_sha256", raw_sha256)
        object.__setattr__(self, "evidence_id", evidence_id)
        object.__setattr__(self, "source_revision", source_revision)


@dataclass(frozen=True, slots=True)
class FeedFeatureFact:
    """Explicit scalar feature extracted upstream from one exact raw feed payload."""

    security_id: str
    decision_at: datetime
    feature_name: str
    feature_value: float
    source_as_of: datetime

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        feature_name = self.feature_name.strip()
        if not security_id:
            raise ModelTrainingError("FEED_FEATURE_SECURITY_ID_REQUIRED")
        if not feature_name:
            raise ModelTrainingError("FEED_FEATURE_NAME_REQUIRED")
        _require_aware(self.decision_at, "FEED_FEATURE_DECISION_AT")
        _require_aware(self.source_as_of, "FEED_FEATURE_SOURCE_AS_OF")
        value = float(self.feature_value)
        if not isfinite(value):
            raise ModelTrainingError("FEED_FEATURE_VALUE_MUST_BE_FINITE")
        if self.source_as_of > self.decision_at:
            raise ModelTrainingError("FEED_FEATURE_SOURCE_AFTER_DECISION")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "feature_name", feature_name)
        object.__setattr__(self, "feature_value", value)


@dataclass(frozen=True, slots=True)
class FeedObservationBatch:
    """Research-only point-in-time features from one validated feed evidence object."""

    evidence: ImmutableFeedEvidence
    observations: tuple[PointInTimeFeatureObservation, ...]
    labels_created: bool = False
    research_only: bool = True
    retuning_authorized: bool = False
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, ImmutableFeedEvidence):
            raise ModelTrainingError("FEED_OBSERVATION_EVIDENCE_TYPE_INVALID")
        if not self.observations:
            raise ModelTrainingError("FEED_OBSERVATION_BATCH_EMPTY")
        if any(
            not isinstance(item, PointInTimeFeatureObservation) for item in self.observations
        ):
            raise ModelTrainingError("FEED_OBSERVATION_TYPE_INVALID")

        canonical = tuple(
            sorted(
                self.observations,
                key=lambda item: (
                    item.security_id,
                    item.decision_at,
                    item.feature_name,
                    item.observation_id,
                ),
            )
        )
        if self.observations != canonical:
            raise ModelTrainingError("FEED_OBSERVATION_BATCH_ORDER_INVALID")
        if len({item.observation_id for item in self.observations}) != len(self.observations):
            raise ModelTrainingError("FEED_OBSERVATION_BATCH_DUPLICATE")
        for observation in self.observations:
            if observation.evidence_id != self.evidence.evidence_id:
                raise ModelTrainingError("FEED_OBSERVATION_EVIDENCE_ID_MISMATCH")
            if observation.source_revision != self.evidence.source_revision:
                raise ModelTrainingError("FEED_OBSERVATION_SOURCE_REVISION_MISMATCH")
            if observation.known_at != self.evidence.captured_at:
                raise ModelTrainingError("FEED_OBSERVATION_KNOWN_AT_MISMATCH")

        if self.labels_created:
            raise ModelTrainingError("FEED_ADAPTER_CANNOT_CREATE_LABELS")
        if not self.research_only:
            raise ModelTrainingError("FEED_OBSERVATION_BATCH_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.retuning_authorized,
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("FEED_OBSERVATION_BATCH_CANNOT_AUTHORIZE_ACTION")

    @property
    def batch_id(self) -> str:
        return _sha(
            {
                "evidence_id": self.evidence.evidence_id,
                "observation_ids": tuple(item.observation_id for item in self.observations),
            }
        )


def validate_immutable_feed_evidence(
    *,
    raw_body: bytes,
    receipt: Mapping[str, Any],
) -> ImmutableFeedEvidence:
    """Validate exact raw bytes against the staging ingestion receipt."""
    if not isinstance(raw_body, bytes):
        raise ModelTrainingError("FEED_RAW_BODY_MUST_BE_BYTES")
    if not raw_body:
        raise ModelTrainingError("FEED_RAW_BODY_EMPTY")
    if receipt.get("schema") != _RECEIPT_SCHEMA:
        raise ModelTrainingError("FEED_RECEIPT_SCHEMA_INVALID")

    provider = str(receipt.get("provider") or "").strip().upper()
    if provider not in _ALLOWED_PROVIDERS:
        raise ModelTrainingError("FEED_RECEIPT_PROVIDER_INVALID")
    target = str(receipt.get("target") or "").strip().upper()
    if not target:
        raise ModelTrainingError("FEED_RECEIPT_TARGET_REQUIRED")
    captured_at = _parse_datetime(receipt.get("captured_at"), "FEED_RECEIPT_CAPTURED_AT")
    capture_mode = str(receipt.get("capture_mode") or "").strip().upper()
    requested_start_date = _parse_date(
        receipt.get("requested_start_date"),
        "FEED_RECEIPT_REQUESTED_START_DATE",
    )
    requested_end_date = _parse_date(
        receipt.get("requested_end_date"),
        "FEED_RECEIPT_REQUESTED_END_DATE",
    )
    known_at_basis = str(receipt.get("known_at_basis") or "").strip().upper()
    historical_known_at_backdating_authorized = receipt.get(
        "historical_known_at_backdating_authorized"
    )
    _validate_capture_lineage(
        capture_mode=capture_mode,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        captured_at=captured_at,
        known_at_basis=known_at_basis,
        historical_known_at_backdating_authorized=(
            historical_known_at_backdating_authorized
        ),
        prefix="FEED_RECEIPT",
    )

    raw_s3_key = str(receipt.get("raw_s3_key") or "").strip()
    _require_raw_key(provider=provider, target=target, raw_s3_key=raw_s3_key)

    raw_sha256 = str(receipt.get("raw_sha256") or "").strip().lower()
    _require_sha256(raw_sha256, "FEED_RECEIPT_RAW_SHA256")
    observed_sha256 = hashlib.sha256(raw_body).hexdigest()
    if observed_sha256 != raw_sha256:
        raise ModelTrainingError("FEED_RAW_SHA256_MISMATCH")

    raw_bytes = receipt.get("raw_bytes")
    if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int) or raw_bytes < 1:
        raise ModelTrainingError("FEED_RECEIPT_RAW_BYTES_INVALID")
    if len(raw_body) != raw_bytes:
        raise ModelTrainingError("FEED_RAW_BYTE_COUNT_MISMATCH")

    if receipt.get("trading_authorized") is not False:
        raise ModelTrainingError("FEED_RECEIPT_TRADING_AUTHORITY_INVALID")
    if receipt.get("live_trading_enabled") is not False:
        raise ModelTrainingError("FEED_RECEIPT_LIVE_AUTHORITY_INVALID")

    identity_payload = _evidence_identity_payload(
        provider=provider,
        target=target,
        captured_at=captured_at,
        capture_mode=capture_mode,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        known_at_basis=known_at_basis,
        historical_known_at_backdating_authorized=(
            historical_known_at_backdating_authorized
        ),
        raw_s3_key=raw_s3_key,
        raw_sha256=raw_sha256,
        raw_bytes=raw_bytes,
    )
    evidence_id = _sha(identity_payload)
    return ImmutableFeedEvidence(
        provider=provider,
        target=target,
        captured_at=captured_at,
        capture_mode=capture_mode,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        known_at_basis=known_at_basis,
        historical_known_at_backdating_authorized=(
            historical_known_at_backdating_authorized
        ),
        raw_s3_key=raw_s3_key,
        raw_sha256=raw_sha256,
        raw_bytes=raw_bytes,
        evidence_id=evidence_id,
        source_revision=f"{_SOURCE_REVISION_PREFIX}:{evidence_id}",
    )


def build_point_in_time_feed_observations(
    *,
    raw_body: bytes,
    receipt: Mapping[str, Any],
    facts: Iterable[FeedFeatureFact],
) -> FeedObservationBatch:
    """Create deterministic model observations without deriving labels or authority."""
    evidence = validate_immutable_feed_evidence(raw_body=raw_body, receipt=receipt)
    normalized = tuple(facts)
    if not normalized:
        raise ModelTrainingError("FEED_FEATURE_FACTS_REQUIRED")

    seen: set[tuple[str, datetime, str]] = set()
    observations: list[PointInTimeFeatureObservation] = []
    for fact in normalized:
        if not isinstance(fact, FeedFeatureFact):
            raise ModelTrainingError("FEED_FEATURE_FACT_TYPE_INVALID")
        key = (fact.security_id, fact.decision_at, fact.feature_name)
        if key in seen:
            raise ModelTrainingError("DUPLICATE_FEED_FEATURE_FACT")
        seen.add(key)
        if fact.source_as_of > evidence.captured_at:
            raise ModelTrainingError("FEED_FEATURE_SOURCE_AFTER_CAPTURE")
        if evidence.captured_at > fact.decision_at:
            raise ModelTrainingError("FEED_FEATURE_CAPTURE_AFTER_DECISION")
        observations.append(
            PointInTimeFeatureObservation(
                security_id=fact.security_id,
                decision_at=fact.decision_at,
                feature_name=fact.feature_name,
                feature_value=fact.feature_value,
                known_at=evidence.captured_at,
                evidence_id=evidence.evidence_id,
                source_revision=evidence.source_revision,
            )
        )

    observations.sort(
        key=lambda item: (
            item.security_id,
            item.decision_at,
            item.feature_name,
            item.observation_id,
        )
    )
    return FeedObservationBatch(evidence=evidence, observations=tuple(observations))


def _evidence_identity_payload(
    *,
    provider: str,
    target: str,
    captured_at: datetime,
    capture_mode: str,
    requested_start_date: date,
    requested_end_date: date,
    known_at_basis: str,
    historical_known_at_backdating_authorized: bool,
    raw_s3_key: str,
    raw_sha256: str,
    raw_bytes: int,
) -> dict[str, Any]:
    return {
        "schema": _RECEIPT_SCHEMA,
        "provider": provider,
        "target": target,
        "captured_at": captured_at.isoformat(),
        "capture_mode": capture_mode,
        "requested_start_date": requested_start_date.isoformat(),
        "requested_end_date": requested_end_date.isoformat(),
        "known_at_basis": known_at_basis,
        "historical_known_at_backdating_authorized": (
            historical_known_at_backdating_authorized
        ),
        "raw_s3_key": raw_s3_key,
        "raw_sha256": raw_sha256,
        "raw_bytes": raw_bytes,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _validate_capture_lineage(
    *,
    capture_mode: str,
    requested_start_date: date,
    requested_end_date: date,
    captured_at: datetime,
    known_at_basis: str,
    historical_known_at_backdating_authorized: Any,
    prefix: str,
) -> None:
    if capture_mode not in _CAPTURE_MODES:
        raise ModelTrainingError(f"{prefix}_CAPTURE_MODE_INVALID")
    if isinstance(requested_start_date, datetime) or not isinstance(
        requested_start_date, date
    ):
        raise ModelTrainingError(f"{prefix}_REQUESTED_START_DATE_INVALID")
    if isinstance(requested_end_date, datetime) or not isinstance(requested_end_date, date):
        raise ModelTrainingError(f"{prefix}_REQUESTED_END_DATE_INVALID")
    if requested_start_date > requested_end_date:
        raise ModelTrainingError(f"{prefix}_REQUESTED_DATE_RANGE_INVALID")
    if requested_end_date > captured_at.date():
        raise ModelTrainingError(f"{prefix}_REQUESTED_END_DATE_AFTER_CAPTURE")
    if capture_mode == _CAPTURE_MODE_HISTORICAL:
        span_days = (requested_end_date - requested_start_date).days + 1
        if span_days > _MAX_HISTORICAL_BACKFILL_DAYS:
            raise ModelTrainingError(f"{prefix}_HISTORICAL_DATE_RANGE_TOO_LARGE")
    if known_at_basis != _KNOWN_AT_BASIS:
        raise ModelTrainingError(f"{prefix}_KNOWN_AT_BASIS_INVALID")
    if historical_known_at_backdating_authorized is not False:
        raise ModelTrainingError(f"{prefix}_HISTORICAL_BACKDATING_AUTHORITY_INVALID")


def _require_raw_key(*, provider: str, target: str, raw_s3_key: str) -> None:
    expected_prefix = f"data-feeds/staging/{provider.lower()}/raw/"
    if not raw_s3_key.startswith(expected_prefix):
        raise ModelTrainingError("FEED_RECEIPT_RAW_KEY_PROVIDER_MISMATCH")
    safe_target = target.replace(".", "_").replace("^", "_")
    if not raw_s3_key.endswith(f"-{safe_target}.json"):
        raise ModelTrainingError("FEED_RECEIPT_RAW_KEY_TARGET_MISMATCH")


def _require_sha256(value: str, code: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ModelTrainingError(f"{code}_INVALID")


def _parse_date(value: Any, code: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ModelTrainingError(f"{code}_REQUIRED")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ModelTrainingError(f"{code}_INVALID") from exc


def _parse_datetime(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ModelTrainingError(f"{code}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ModelTrainingError(f"{code}_INVALID") from exc
    _require_aware(parsed, code)
    return parsed


def _require_aware(value: datetime, code: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelTrainingError(f"{code}_MUST_BE_TIMEZONE_AWARE")


def _sha(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
