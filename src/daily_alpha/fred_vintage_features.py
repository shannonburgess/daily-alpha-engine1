"""Revision-aware FRED vintage evidence for point-in-time model features.

Generic staging receipts prove when Daily Alpha captured raw bytes. FRED vintage payloads
carry an independent real-time validity interval that can establish earlier historical
availability. Because FRED's real-time fields are date-granular, this adapter deliberately
uses noon UTC on the following calendar day as ``known_at`` instead of inventing a same-day
release timestamp.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from typing import Any

from .model_dataset_builder import PointInTimeFeatureObservation
from .model_feed_observations import ImmutableFeedEvidence, validate_immutable_feed_evidence
from .model_training import ModelTrainingError

_FRED_VINTAGE_MODE = "FRED_VINTAGE_BACKFILL"
_FRED_VINTAGE_SEMANTICS = "FRED_REALTIME_INTERVAL"
_CAPTURE_ONLY_BASIS = "CAPTURED_AT_ONLY"
_CONSERVATIVE_KNOWN_AT_HOUR_UTC = 12


@dataclass(frozen=True, slots=True)
class FredVintageObservation:
    """One FRED value and the provider-declared real-time validity interval."""

    series_id: str
    observation_date: date
    realtime_start: date
    realtime_end: date
    value: float | None

    def __post_init__(self) -> None:
        series_id = self.series_id.strip().upper()
        if not series_id:
            raise ModelTrainingError("FRED_VINTAGE_SERIES_ID_REQUIRED")
        if self.realtime_end < self.realtime_start:
            raise ModelTrainingError("FRED_VINTAGE_REALTIME_INTERVAL_INVALID")
        if self.value is not None:
            value = float(self.value)
            if not isfinite(value):
                raise ModelTrainingError("FRED_VINTAGE_VALUE_MUST_BE_FINITE")
            object.__setattr__(self, "value", value)
        object.__setattr__(self, "series_id", series_id)

    @property
    def vintage_id(self) -> str:
        return _sha(
            {
                "series_id": self.series_id,
                "observation_date": self.observation_date.isoformat(),
                "realtime_start": self.realtime_start.isoformat(),
                "realtime_end": self.realtime_end.isoformat(),
                "value": self.value,
            }
        )


@dataclass(frozen=True, slots=True)
class FredVintageEvidenceSet:
    """Exact raw FRED evidence plus its requested historical vintage boundary."""

    base_evidence: ImmutableFeedEvidence
    requested_start_date: date
    requested_end_date: date
    vintage_as_of_date: date
    observations: tuple[FredVintageObservation, ...]
    provider_vintage_semantics: str = _FRED_VINTAGE_SEMANTICS
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.base_evidence.provider != "FRED":
            raise ModelTrainingError("FRED_VINTAGE_EVIDENCE_REQUIRES_FRED_PROVIDER")
        if self.requested_end_date < self.requested_start_date:
            raise ModelTrainingError("FRED_VINTAGE_REQUEST_RANGE_INVALID")
        if self.requested_end_date > self.vintage_as_of_date:
            raise ModelTrainingError("FRED_VINTAGE_OBSERVATION_END_AFTER_VINTAGE")
        if self.vintage_as_of_date > self.base_evidence.captured_at.date():
            raise ModelTrainingError("FRED_VINTAGE_DATE_AFTER_CAPTURE")
        if self.provider_vintage_semantics != _FRED_VINTAGE_SEMANTICS:
            raise ModelTrainingError("FRED_VINTAGE_SEMANTICS_INVALID")
        if not self.observations:
            raise ModelTrainingError("FRED_VINTAGE_OBSERVATIONS_EMPTY")
        if len({item.observation_date for item in self.observations}) != len(self.observations):
            raise ModelTrainingError("FRED_VINTAGE_OBSERVATION_DATE_DUPLICATE")
        canonical = tuple(
            sorted(
                self.observations,
                key=lambda item: (
                    item.observation_date,
                    item.realtime_start,
                    item.realtime_end,
                    item.vintage_id,
                ),
            )
        )
        if self.observations != canonical:
            raise ModelTrainingError("FRED_VINTAGE_OBSERVATION_ORDER_INVALID")
        for item in self.observations:
            if item.series_id != self.base_evidence.target:
                raise ModelTrainingError("FRED_VINTAGE_SERIES_TARGET_MISMATCH")
            if not self.requested_start_date <= item.observation_date <= self.requested_end_date:
                raise ModelTrainingError("FRED_VINTAGE_OBSERVATION_OUTSIDE_REQUEST_RANGE")
            if not item.realtime_start <= self.vintage_as_of_date <= item.realtime_end:
                raise ModelTrainingError("FRED_VINTAGE_REALTIME_INTERVAL_MISSES_REQUESTED_VINTAGE")
        if not self.research_only:
            raise ModelTrainingError("FRED_VINTAGE_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        if self.trading_authorized or self.live_trading_enabled:
            raise ModelTrainingError("FRED_VINTAGE_EVIDENCE_CANNOT_AUTHORIZE_TRADING")

    @property
    def evidence_id(self) -> str:
        return _sha(
            {
                "base_evidence_id": self.base_evidence.evidence_id,
                "requested_start_date": self.requested_start_date.isoformat(),
                "requested_end_date": self.requested_end_date.isoformat(),
                "vintage_as_of_date": self.vintage_as_of_date.isoformat(),
                "provider_vintage_semantics": self.provider_vintage_semantics,
                "observation_ids": tuple(item.vintage_id for item in self.observations),
            }
        )


@dataclass(frozen=True, slots=True)
class FredVintageFeatureResult:
    """One selected vintage feature with no label, promotion, or execution authority."""

    evidence: FredVintageEvidenceSet
    selected_vintage: FredVintageObservation
    observation: PointInTimeFeatureObservation
    labels_created: bool = False
    research_only: bool = True
    retuning_authorized: bool = False
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.selected_vintage not in self.evidence.observations:
            raise ModelTrainingError("FRED_VINTAGE_SELECTION_NOT_IN_EVIDENCE")
        expected_evidence_id = _selected_evidence_id(self.evidence, self.selected_vintage)
        if self.observation.evidence_id != expected_evidence_id:
            raise ModelTrainingError("FRED_VINTAGE_FEATURE_EVIDENCE_ID_MISMATCH")
        if self.observation.source_revision != f"fred-vintage-v1:{expected_evidence_id}":
            raise ModelTrainingError("FRED_VINTAGE_FEATURE_SOURCE_REVISION_MISMATCH")
        expected_known_at = conservative_fred_vintage_known_at(self.selected_vintage.realtime_start)
        if self.observation.known_at != expected_known_at:
            raise ModelTrainingError("FRED_VINTAGE_FEATURE_KNOWN_AT_MISMATCH")
        if self.observation.feature_value != self.selected_vintage.value:
            raise ModelTrainingError("FRED_VINTAGE_FEATURE_VALUE_MISMATCH")
        if self.labels_created:
            raise ModelTrainingError("FRED_VINTAGE_ADAPTER_CANNOT_CREATE_LABELS")
        if not self.research_only:
            raise ModelTrainingError("FRED_VINTAGE_FEATURE_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.retuning_authorized,
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("FRED_VINTAGE_FEATURE_CANNOT_AUTHORIZE_ACTION")


def parse_fred_vintage_evidence(
    *,
    raw_body: bytes,
    receipt: Mapping[str, Any],
) -> FredVintageEvidenceSet:
    """Hash-validate a captured FRED vintage payload and normalize its real-time intervals."""
    base_evidence = validate_immutable_feed_evidence(raw_body=raw_body, receipt=receipt)
    if base_evidence.provider != "FRED":
        raise ModelTrainingError("FRED_VINTAGE_EVIDENCE_REQUIRES_FRED_PROVIDER")
    if str(receipt.get("capture_mode") or "").strip().upper() != _FRED_VINTAGE_MODE:
        raise ModelTrainingError("FRED_VINTAGE_CAPTURE_MODE_REQUIRED")
    if str(receipt.get("known_at_basis") or "").strip().upper() != _CAPTURE_ONLY_BASIS:
        raise ModelTrainingError("FRED_VINTAGE_GENERIC_KNOWN_AT_BASIS_INVALID")
    if receipt.get("historical_known_at_backdating_authorized") is not False:
        raise ModelTrainingError("FRED_VINTAGE_GENERIC_BACKDATING_MUST_REMAIN_FALSE")
    semantics = str(receipt.get("provider_vintage_semantics") or "").strip().upper()
    if semantics != _FRED_VINTAGE_SEMANTICS:
        raise ModelTrainingError("FRED_VINTAGE_SEMANTICS_INVALID")

    requested_start = _parse_date(receipt.get("requested_start_date"), "FRED_VINTAGE_START_DATE")
    requested_end = _parse_date(receipt.get("requested_end_date"), "FRED_VINTAGE_END_DATE")
    vintage_as_of = _parse_date(receipt.get("vintage_as_of_date"), "FRED_VINTAGE_AS_OF_DATE")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelTrainingError("FRED_VINTAGE_RAW_JSON_INVALID") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise ModelTrainingError("FRED_VINTAGE_PAYLOAD_SHAPE_INVALID")

    observations: list[FredVintageObservation] = []
    for raw in payload["observations"]:
        if not isinstance(raw, dict):
            raise ModelTrainingError("FRED_VINTAGE_OBSERVATION_ITEM_INVALID")
        raw_value = str(raw.get("value") or "").strip()
        if not raw_value:
            raise ModelTrainingError("FRED_VINTAGE_VALUE_REQUIRED")
        if raw_value == ".":
            value: float | None = None
        else:
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ModelTrainingError("FRED_VINTAGE_VALUE_INVALID") from exc
        observations.append(
            FredVintageObservation(
                series_id=base_evidence.target,
                observation_date=_parse_date(raw.get("date"), "FRED_VINTAGE_OBSERVATION_DATE"),
                realtime_start=_parse_date(raw.get("realtime_start"), "FRED_VINTAGE_REALTIME_START"),
                realtime_end=_parse_date(raw.get("realtime_end"), "FRED_VINTAGE_REALTIME_END"),
                value=value,
            )
        )

    observations.sort(
        key=lambda item: (
            item.observation_date,
            item.realtime_start,
            item.realtime_end,
            item.vintage_id,
        )
    )
    return FredVintageEvidenceSet(
        base_evidence=base_evidence,
        requested_start_date=requested_start,
        requested_end_date=requested_end,
        vintage_as_of_date=vintage_as_of,
        observations=tuple(observations),
        provider_vintage_semantics=semantics,
    )


def build_fred_vintage_feature(
    *,
    raw_body: bytes,
    receipt: Mapping[str, Any],
    security_id: str,
    decision_at: datetime,
    feature_name: str | None = None,
) -> FredVintageFeatureResult:
    """Select the latest eligible historical FRED value without look-ahead or revision leakage."""
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ModelTrainingError("FRED_VINTAGE_DECISION_AT_MUST_BE_TIMEZONE_AWARE")
    evidence = parse_fred_vintage_evidence(raw_body=raw_body, receipt=receipt)
    if evidence.vintage_as_of_date > decision_at.date():
        raise ModelTrainingError("FRED_VINTAGE_QUERY_AFTER_DECISION_DATE")

    eligible = tuple(
        item for item in evidence.observations if item.observation_date <= decision_at.date()
    )
    if not eligible:
        raise ModelTrainingError("FRED_VINTAGE_NO_OBSERVATION_BY_DECISION")
    selected = max(eligible, key=lambda item: item.observation_date)
    if selected.value is None:
        raise ModelTrainingError("FRED_VINTAGE_LATEST_VALUE_MISSING")

    known_at = conservative_fred_vintage_known_at(selected.realtime_start)
    if known_at > decision_at:
        raise ModelTrainingError("FRED_VINTAGE_NOT_KNOWN_BY_DECISION")

    evidence_id = _selected_evidence_id(evidence, selected)
    normalized_feature_name = (feature_name or f"fred_{evidence.base_evidence.target.lower()}").strip()
    if not normalized_feature_name:
        raise ModelTrainingError("FRED_VINTAGE_FEATURE_NAME_REQUIRED")
    observation = PointInTimeFeatureObservation(
        security_id=security_id,
        decision_at=decision_at,
        feature_name=normalized_feature_name,
        feature_value=selected.value,
        known_at=known_at,
        evidence_id=evidence_id,
        source_revision=f"fred-vintage-v1:{evidence_id}",
    )
    return FredVintageFeatureResult(
        evidence=evidence,
        selected_vintage=selected,
        observation=observation,
    )


def conservative_fred_vintage_known_at(realtime_start: date) -> datetime:
    """Return a deliberately late timestamp for FRED's date-only real-time boundary."""
    next_day = realtime_start + timedelta(days=1)
    return datetime.combine(
        next_day,
        time(hour=_CONSERVATIVE_KNOWN_AT_HOUR_UTC),
        tzinfo=UTC,
    )


def _selected_evidence_id(
    evidence: FredVintageEvidenceSet,
    selected: FredVintageObservation,
) -> str:
    return _sha(
        {
            "fred_vintage_evidence_id": evidence.evidence_id,
            "selected_vintage_id": selected.vintage_id,
            "conservative_known_at": conservative_fred_vintage_known_at(
                selected.realtime_start
            ).isoformat(),
        }
    )


def _parse_date(value: Any, code: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ModelTrainingError(f"{code}_REQUIRED")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ModelTrainingError(f"{code}_INVALID") from exc


def _sha(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
