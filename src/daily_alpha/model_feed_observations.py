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
from datetime import datetime
from math import isfinite
from typing import Any

from .model_dataset_builder import PointInTimeFeatureObservation
from .model_training import ModelTrainingError

_RECEIPT_SCHEMA = "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1"
_ALLOWED_PROVIDERS = frozenset({"MASSIVE", "TIINGO", "FRED"})


@dataclass(frozen=True, slots=True)
class ImmutableFeedEvidence:
    """Validated identity for one immutable raw provider response and receipt."""

    provider: str
    target: str
    captured_at: datetime
    raw_s3_key: str
    raw_sha256: str
    raw_bytes: int
    evidence_id: str
    source_revision: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.research_only:
            raise ModelTrainingError("FEED_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        if self.trading_authorized or self.live_trading_enabled:
            raise ModelTrainingError("FEED_EVIDENCE_CANNOT_AUTHORIZE_TRADING")


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
        if not self.observations:
            raise ModelTrainingError("FEED_OBSERVATION_BATCH_EMPTY")
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

    raw_s3_key = str(receipt.get("raw_s3_key") or "").strip()
    expected_prefix = f"data-feeds/staging/{provider.lower()}/raw/"
    if not raw_s3_key.startswith(expected_prefix):
        raise ModelTrainingError("FEED_RECEIPT_RAW_KEY_PROVIDER_MISMATCH")

    raw_sha256 = str(receipt.get("raw_sha256") or "").strip().lower()
    if len(raw_sha256) != 64 or any(char not in "0123456789abcdef" for char in raw_sha256):
        raise ModelTrainingError("FEED_RECEIPT_RAW_SHA256_INVALID")
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

    identity_payload = {
        "schema": _RECEIPT_SCHEMA,
        "provider": provider,
        "target": target,
        "captured_at": captured_at.isoformat(),
        "raw_s3_key": raw_s3_key,
        "raw_sha256": raw_sha256,
        "raw_bytes": raw_bytes,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    evidence_id = _sha(identity_payload)
    return ImmutableFeedEvidence(
        provider=provider,
        target=target,
        captured_at=captured_at,
        raw_s3_key=raw_s3_key,
        raw_sha256=raw_sha256,
        raw_bytes=raw_bytes,
        evidence_id=evidence_id,
        source_revision=f"feed-receipt-v1:{evidence_id}",
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


def _parse_datetime(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ModelTrainingError(f"{code}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
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
