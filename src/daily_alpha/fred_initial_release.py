"""Provider-specific FRED/ALFRED initial-release point-in-time evidence.

Generic staging feed receipts deliberately keep ``known_at`` at transport capture time.
This module is a narrower, stronger historical-availability contract for FRED responses
that explicitly declare ``output_type=4`` (initial release only). FRED documents its
real-time period as the period when information was known. Because the JSON exposes a
release date but not an intraday release timestamp, this adapter conservatively makes a
vintage eligible only at 00:00 UTC on the following calendar day.

The transport receipt remains immutable evidence of what Daily Alpha captured. The
historical model ``known_at`` claim is derived only from the provider-specific initial-
release row and is bound to both that row and the exact raw receipt evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from typing import Any, Mapping

from .model_dataset_builder import PointInTimeFeatureObservation
from .model_feed_observations import ImmutableFeedEvidence, validate_immutable_feed_evidence
from .model_training import ModelTrainingError

FRED_INITIAL_RELEASE_OUTPUT_TYPE = 4
FRED_INITIAL_RELEASE_CONTRACT = "FRED_OUTPUT_TYPE_4_INITIAL_RELEASE_V1"
FRED_INITIAL_RELEASE_KNOWN_AT_POLICY = "NEXT_UTC_DAY_AFTER_REALTIME_START"
_SOURCE_REVISION_PREFIX = "fred-initial-release-v1"


@dataclass(frozen=True, slots=True)
class FredInitialReleaseObservation:
    """One initial-release FRED observation bound to immutable raw evidence."""

    series_id: str
    observation_date: date
    realtime_start: date
    realtime_end: date
    value: float
    raw_evidence_id: str
    raw_source_revision: str

    def __post_init__(self) -> None:
        series_id = self.series_id.strip().upper()
        raw_evidence_id = self.raw_evidence_id.strip().lower()
        raw_source_revision = self.raw_source_revision.strip()
        if not series_id:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_SERIES_REQUIRED")
        if self.realtime_end < self.realtime_start:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_REALTIME_RANGE_INVALID")
        value = float(self.value)
        if not isfinite(value):
            raise ModelTrainingError("FRED_INITIAL_RELEASE_VALUE_MUST_BE_FINITE")
        if len(raw_evidence_id) != 64 or any(
            char not in "0123456789abcdef" for char in raw_evidence_id
        ):
            raise ModelTrainingError("FRED_INITIAL_RELEASE_RAW_EVIDENCE_ID_INVALID")
        if not raw_source_revision:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_RAW_SOURCE_REVISION_REQUIRED")
        object.__setattr__(self, "series_id", series_id)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "raw_evidence_id", raw_evidence_id)
        object.__setattr__(self, "raw_source_revision", raw_source_revision)

    @property
    def known_at(self) -> datetime:
        """Conservative historical availability boundary from date-only FRED evidence."""
        return datetime.combine(
            self.realtime_start + timedelta(days=1),
            time.min,
            tzinfo=UTC,
        )

    @property
    def row_id(self) -> str:
        return _sha(
            {
                "contract": FRED_INITIAL_RELEASE_CONTRACT,
                "series_id": self.series_id,
                "observation_date": self.observation_date.isoformat(),
                "realtime_start": self.realtime_start.isoformat(),
                "realtime_end": self.realtime_end.isoformat(),
                "value": self.value,
                "raw_evidence_id": self.raw_evidence_id,
                "raw_source_revision": self.raw_source_revision,
            }
        )

    @property
    def source_revision(self) -> str:
        return (
            f"{_SOURCE_REVISION_PREFIX}:{self.row_id}:"
            f"raw:{self.raw_evidence_id}"
        )


@dataclass(frozen=True, slots=True)
class FredInitialReleaseBatch:
    """Validated FRED initial-release history; research evidence only."""

    evidence: ImmutableFeedEvidence
    observations: tuple[FredInitialReleaseObservation, ...]
    output_type: int = FRED_INITIAL_RELEASE_OUTPUT_TYPE
    availability_contract: str = FRED_INITIAL_RELEASE_CONTRACT
    known_at_policy: str = FRED_INITIAL_RELEASE_KNOWN_AT_POLICY
    research_only: bool = True
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.evidence.provider != "FRED":
            raise ModelTrainingError("FRED_INITIAL_RELEASE_PROVIDER_REQUIRED")
        if self.evidence.capture_mode != "HISTORICAL_BACKFILL":
            raise ModelTrainingError("FRED_INITIAL_RELEASE_HISTORICAL_CAPTURE_REQUIRED")
        if self.output_type != FRED_INITIAL_RELEASE_OUTPUT_TYPE:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_OUTPUT_TYPE_INVALID")
        if self.availability_contract != FRED_INITIAL_RELEASE_CONTRACT:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_CONTRACT_INVALID")
        if self.known_at_policy != FRED_INITIAL_RELEASE_KNOWN_AT_POLICY:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_KNOWN_AT_POLICY_INVALID")
        if not self.observations:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_OBSERVATIONS_REQUIRED")

        canonical = tuple(
            sorted(
                self.observations,
                key=lambda item: (
                    item.observation_date,
                    item.realtime_start,
                    item.row_id,
                ),
            )
        )
        if canonical != self.observations:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_ORDER_INVALID")
        if len({item.row_id for item in self.observations}) != len(self.observations):
            raise ModelTrainingError("FRED_INITIAL_RELEASE_DUPLICATE_ROW")
        for item in self.observations:
            if item.series_id != self.evidence.target:
                raise ModelTrainingError("FRED_INITIAL_RELEASE_TARGET_MISMATCH")
            if item.raw_evidence_id != self.evidence.evidence_id:
                raise ModelTrainingError("FRED_INITIAL_RELEASE_EVIDENCE_MISMATCH")
            if item.raw_source_revision != self.evidence.source_revision:
                raise ModelTrainingError("FRED_INITIAL_RELEASE_SOURCE_REVISION_MISMATCH")
            if item.realtime_start > self.evidence.captured_at.date():
                raise ModelTrainingError("FRED_INITIAL_RELEASE_AFTER_CAPTURE")

        if not self.research_only:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("FRED_INITIAL_RELEASE_CANNOT_AUTHORIZE_ACTION")

    @property
    def batch_id(self) -> str:
        return _sha(
            {
                "contract": self.availability_contract,
                "known_at_policy": self.known_at_policy,
                "output_type": self.output_type,
                "raw_evidence_id": self.evidence.evidence_id,
                "row_ids": tuple(item.row_id for item in self.observations),
            }
        )


def parse_fred_initial_release_history(
    *,
    raw_body: bytes,
    receipt: Mapping[str, Any],
) -> FredInitialReleaseBatch:
    """Validate an archived FRED ``output_type=4`` response and its release lineage."""
    evidence = validate_immutable_feed_evidence(raw_body=raw_body, receipt=receipt)
    if evidence.provider != "FRED":
        raise ModelTrainingError("FRED_INITIAL_RELEASE_PROVIDER_REQUIRED")
    if evidence.capture_mode != "HISTORICAL_BACKFILL":
        raise ModelTrainingError("FRED_INITIAL_RELEASE_HISTORICAL_CAPTURE_REQUIRED")

    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise ModelTrainingError("FRED_INITIAL_RELEASE_JSON_OBJECT_REQUIRED")

    output_type = payload.get("output_type")
    if isinstance(output_type, bool):
        raise ModelTrainingError("FRED_INITIAL_RELEASE_OUTPUT_TYPE_INVALID")
    try:
        output_type = int(output_type)
    except (TypeError, ValueError) as exc:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_OUTPUT_TYPE_INVALID") from exc
    if output_type != FRED_INITIAL_RELEASE_OUTPUT_TYPE:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_OUTPUT_TYPE_REQUIRED")

    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_OBSERVATIONS_REQUIRED")

    by_observation_date: dict[date, FredInitialReleaseObservation] = {}
    for raw in raw_observations:
        if not isinstance(raw, dict):
            raise ModelTrainingError("FRED_INITIAL_RELEASE_ROW_OBJECT_REQUIRED")
        observation_date = _parse_date(raw.get("date"), "FRED_INITIAL_RELEASE_OBSERVATION_DATE")
        realtime_start = _parse_date(
            raw.get("realtime_start"),
            "FRED_INITIAL_RELEASE_REALTIME_START",
        )
        realtime_end = _parse_date(
            raw.get("realtime_end"),
            "FRED_INITIAL_RELEASE_REALTIME_END",
        )
        raw_value = raw.get("value")
        if raw_value in {None, ".", ""}:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_VALUE_MISSING")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ModelTrainingError("FRED_INITIAL_RELEASE_VALUE_INVALID") from exc
        observation = FredInitialReleaseObservation(
            series_id=evidence.target,
            observation_date=observation_date,
            realtime_start=realtime_start,
            realtime_end=realtime_end,
            value=value,
            raw_evidence_id=evidence.evidence_id,
            raw_source_revision=evidence.source_revision,
        )
        if observation.realtime_start > evidence.captured_at.date():
            raise ModelTrainingError("FRED_INITIAL_RELEASE_AFTER_CAPTURE")
        existing = by_observation_date.get(observation_date)
        if existing is not None:
            if existing.row_id == observation.row_id:
                continue
            raise ModelTrainingError("FRED_INITIAL_RELEASE_CONFLICTING_OBSERVATION_DATE")
        by_observation_date[observation_date] = observation

    observations = tuple(
        sorted(
            by_observation_date.values(),
            key=lambda item: (
                item.observation_date,
                item.realtime_start,
                item.row_id,
            ),
        )
    )
    return FredInitialReleaseBatch(evidence=evidence, observations=observations)


def build_fred_initial_release_feature(
    *,
    batch: FredInitialReleaseBatch,
    security_id: str,
    decision_at: datetime,
    feature_name: str,
) -> PointInTimeFeatureObservation:
    """Select the latest initial-release value provably available by ``decision_at``."""
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_DECISION_AT_MUST_BE_AWARE")
    security_id = security_id.strip().upper()
    feature_name = feature_name.strip()
    if not security_id:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_SECURITY_ID_REQUIRED")
    if not feature_name:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_FEATURE_NAME_REQUIRED")

    eligible = tuple(
        item
        for item in batch.observations
        if item.observation_date <= decision_at.date() and item.known_at <= decision_at
    )
    if not eligible:
        raise ModelTrainingError("FRED_INITIAL_RELEASE_NO_VALUE_KNOWN_AT_DECISION")
    selected = max(
        eligible,
        key=lambda item: (
            item.observation_date,
            item.known_at,
            item.row_id,
        ),
    )
    return PointInTimeFeatureObservation(
        security_id=security_id,
        decision_at=decision_at,
        feature_name=feature_name,
        feature_value=selected.value,
        known_at=selected.known_at,
        evidence_id=selected.row_id,
        source_revision=selected.source_revision,
    )


def _parse_date(value: Any, code: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ModelTrainingError(f"{code}_REQUIRED")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ModelTrainingError(f"{code}_INVALID") from exc


def _sha(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
