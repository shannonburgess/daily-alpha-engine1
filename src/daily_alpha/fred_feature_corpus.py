"""Deterministic macro-feature corpus assembly from FRED initial-release evidence.

This module does not download data and does not create labels. It converts already-
validated ``FRED_OUTPUT_TYPE_4_INITIAL_RELEASE_V1`` batches into point-in-time feature
observations for declared historical decision boundaries.

Multiple bounded captures may be supplied for one series, but their observation dates
must not overlap. That keeps the evidence source for every historical value unambiguous
instead of silently choosing among repeated captures of the same provider row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from .fred_initial_release import FredInitialReleaseBatch, FredInitialReleaseObservation
from .model_dataset_builder import PointInTimeFeatureObservation
from .model_training import ModelTrainingError

_CORPUS_CONTRACT = "FRED_INITIAL_RELEASE_MACRO_FEATURE_CORPUS_V1"


@dataclass(frozen=True, slots=True)
class FredMacroFeatureSpec:
    """One declared mapping from a FRED series to a model feature name."""

    series_id: str
    feature_name: str

    def __post_init__(self) -> None:
        series_id = self.series_id.strip().upper()
        feature_name = self.feature_name.strip()
        if not series_id:
            raise ModelTrainingError("FRED_CORPUS_SERIES_ID_REQUIRED")
        if not feature_name:
            raise ModelTrainingError("FRED_CORPUS_FEATURE_NAME_REQUIRED")
        object.__setattr__(self, "series_id", series_id)
        object.__setattr__(self, "feature_name", feature_name)

    @property
    def spec_id(self) -> str:
        return _sha(
            {
                "contract": _CORPUS_CONTRACT,
                "series_id": self.series_id,
                "feature_name": self.feature_name,
            }
        )


@dataclass(frozen=True, slots=True)
class FredMacroFeatureCorpus:
    """Immutable research-only FRED macro feature observations."""

    feature_specs: tuple[FredMacroFeatureSpec, ...]
    security_ids: tuple[str, ...]
    decision_times: tuple[datetime, ...]
    batch_ids: tuple[str, ...]
    observations: tuple[PointInTimeFeatureObservation, ...]
    contract: str = _CORPUS_CONTRACT
    research_only: bool = True
    labels_created: bool = False
    retuning_authorized: bool = False
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.contract != _CORPUS_CONTRACT:
            raise ModelTrainingError("FRED_CORPUS_CONTRACT_INVALID")
        if not self.feature_specs:
            raise ModelTrainingError("FRED_CORPUS_FEATURE_SPECS_REQUIRED")
        if not self.security_ids:
            raise ModelTrainingError("FRED_CORPUS_SECURITY_IDS_REQUIRED")
        if not self.decision_times:
            raise ModelTrainingError("FRED_CORPUS_DECISION_TIMES_REQUIRED")
        if not self.batch_ids:
            raise ModelTrainingError("FRED_CORPUS_BATCH_IDS_REQUIRED")
        if not self.observations:
            raise ModelTrainingError("FRED_CORPUS_OBSERVATIONS_REQUIRED")

        canonical_specs = tuple(
            sorted(self.feature_specs, key=lambda item: (item.feature_name, item.series_id))
        )
        if canonical_specs != self.feature_specs:
            raise ModelTrainingError("FRED_CORPUS_FEATURE_SPEC_ORDER_INVALID")
        if len({item.spec_id for item in self.feature_specs}) != len(self.feature_specs):
            raise ModelTrainingError("FRED_CORPUS_DUPLICATE_FEATURE_SPEC")

        canonical_security_ids = tuple(sorted(self.security_ids))
        if canonical_security_ids != self.security_ids:
            raise ModelTrainingError("FRED_CORPUS_SECURITY_ORDER_INVALID")
        if len(set(self.security_ids)) != len(self.security_ids):
            raise ModelTrainingError("FRED_CORPUS_DUPLICATE_SECURITY")

        canonical_decisions = tuple(sorted(self.decision_times))
        if canonical_decisions != self.decision_times:
            raise ModelTrainingError("FRED_CORPUS_DECISION_ORDER_INVALID")
        if len(set(self.decision_times)) != len(self.decision_times):
            raise ModelTrainingError("FRED_CORPUS_DUPLICATE_DECISION")
        for decision_at in self.decision_times:
            _require_aware(decision_at, "FRED_CORPUS_DECISION_AT")

        if tuple(sorted(self.batch_ids)) != self.batch_ids:
            raise ModelTrainingError("FRED_CORPUS_BATCH_ID_ORDER_INVALID")
        if len(set(self.batch_ids)) != len(self.batch_ids):
            raise ModelTrainingError("FRED_CORPUS_DUPLICATE_BATCH_ID")

        canonical_observations = tuple(
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
        if canonical_observations != self.observations:
            raise ModelTrainingError("FRED_CORPUS_OBSERVATION_ORDER_INVALID")
        if len({item.observation_id for item in self.observations}) != len(self.observations):
            raise ModelTrainingError("FRED_CORPUS_DUPLICATE_OBSERVATION")

        expected_count = (
            len(self.feature_specs) * len(self.security_ids) * len(self.decision_times)
        )
        if len(self.observations) != expected_count:
            raise ModelTrainingError("FRED_CORPUS_OBSERVATION_MATRIX_INCOMPLETE")

        if self.labels_created:
            raise ModelTrainingError("FRED_CORPUS_CANNOT_CREATE_LABELS")
        if not self.research_only:
            raise ModelTrainingError("FRED_CORPUS_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.retuning_authorized,
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("FRED_CORPUS_CANNOT_AUTHORIZE_ACTION")

    @property
    def source_revisions(self) -> tuple[str, ...]:
        return tuple(sorted({item.source_revision for item in self.observations}))

    @property
    def corpus_id(self) -> str:
        return _sha(
            {
                "contract": self.contract,
                "feature_spec_ids": tuple(item.spec_id for item in self.feature_specs),
                "security_ids": self.security_ids,
                "decision_times": tuple(item.isoformat() for item in self.decision_times),
                "batch_ids": self.batch_ids,
                "observation_ids": tuple(item.observation_id for item in self.observations),
            }
        )


def build_fred_macro_feature_corpus(
    *,
    batches: Iterable[FredInitialReleaseBatch],
    feature_specs: Iterable[FredMacroFeatureSpec],
    security_ids: Iterable[str],
    decision_times: Iterable[datetime],
) -> FredMacroFeatureCorpus:
    """Build a complete declared macro-feature matrix from initial-release evidence."""
    normalized_batches = tuple(batches)
    if not normalized_batches:
        raise ModelTrainingError("FRED_CORPUS_BATCHES_REQUIRED")
    if any(not isinstance(item, FredInitialReleaseBatch) for item in normalized_batches):
        raise ModelTrainingError("FRED_CORPUS_BATCH_TYPE_INVALID")

    normalized_specs = tuple(feature_specs)
    if not normalized_specs:
        raise ModelTrainingError("FRED_CORPUS_FEATURE_SPECS_REQUIRED")
    if any(not isinstance(item, FredMacroFeatureSpec) for item in normalized_specs):
        raise ModelTrainingError("FRED_CORPUS_FEATURE_SPEC_TYPE_INVALID")
    normalized_specs = tuple(
        sorted(normalized_specs, key=lambda item: (item.feature_name, item.series_id))
    )
    if len({item.series_id for item in normalized_specs}) != len(normalized_specs):
        raise ModelTrainingError("FRED_CORPUS_ONE_FEATURE_PER_SERIES_REQUIRED")
    if len({item.feature_name for item in normalized_specs}) != len(normalized_specs):
        raise ModelTrainingError("FRED_CORPUS_FEATURE_NAMES_MUST_BE_UNIQUE")

    normalized_security_ids = tuple(
        sorted({str(item).strip().upper() for item in security_ids if str(item).strip()})
    )
    if not normalized_security_ids:
        raise ModelTrainingError("FRED_CORPUS_SECURITY_IDS_REQUIRED")

    raw_decisions = tuple(decision_times)
    if not raw_decisions:
        raise ModelTrainingError("FRED_CORPUS_DECISION_TIMES_REQUIRED")
    for decision_at in raw_decisions:
        _require_aware(decision_at, "FRED_CORPUS_DECISION_AT")
    if len(set(raw_decisions)) != len(raw_decisions):
        raise ModelTrainingError("FRED_CORPUS_DUPLICATE_DECISION")
    normalized_decisions = tuple(sorted(raw_decisions))

    spec_series = {item.series_id for item in normalized_specs}
    by_series: dict[str, list[FredInitialReleaseBatch]] = {}
    for batch in normalized_batches:
        series_id = batch.evidence.target
        if series_id not in spec_series:
            raise ModelTrainingError("FRED_CORPUS_UNDECLARED_SERIES")
        by_series.setdefault(series_id, []).append(batch)
    if set(by_series) != spec_series:
        raise ModelTrainingError("FRED_CORPUS_DECLARED_SERIES_MISSING")

    history_by_series: dict[str, tuple[FredInitialReleaseObservation, ...]] = {}
    for series_id, series_batches in by_series.items():
        seen_dates = set()
        observations: list[FredInitialReleaseObservation] = []
        for batch in sorted(series_batches, key=lambda item: item.batch_id):
            for observation in batch.observations:
                if observation.observation_date in seen_dates:
                    raise ModelTrainingError("FRED_CORPUS_OVERLAPPING_BATCH_DATE")
                seen_dates.add(observation.observation_date)
                observations.append(observation)
        observations.sort(
            key=lambda item: (item.observation_date, item.known_at, item.row_id)
        )
        history_by_series[series_id] = tuple(observations)

    point_in_time_observations: list[PointInTimeFeatureObservation] = []
    for security_id in normalized_security_ids:
        for decision_at in normalized_decisions:
            for spec in normalized_specs:
                selected = _select_known_observation(
                    history_by_series[spec.series_id],
                    decision_at=decision_at,
                )
                point_in_time_observations.append(
                    PointInTimeFeatureObservation(
                        security_id=security_id,
                        decision_at=decision_at,
                        feature_name=spec.feature_name,
                        feature_value=selected.value,
                        known_at=selected.known_at,
                        evidence_id=selected.row_id,
                        source_revision=selected.source_revision,
                    )
                )

    point_in_time_observations.sort(
        key=lambda item: (
            item.security_id,
            item.decision_at,
            item.feature_name,
            item.observation_id,
        )
    )
    return FredMacroFeatureCorpus(
        feature_specs=normalized_specs,
        security_ids=normalized_security_ids,
        decision_times=normalized_decisions,
        batch_ids=tuple(sorted({item.batch_id for item in normalized_batches})),
        observations=tuple(point_in_time_observations),
    )


def _select_known_observation(
    observations: tuple[FredInitialReleaseObservation, ...],
    *,
    decision_at: datetime,
) -> FredInitialReleaseObservation:
    eligible = tuple(
        item
        for item in observations
        if item.observation_date <= decision_at.date() and item.known_at <= decision_at
    )
    if not eligible:
        raise ModelTrainingError("FRED_CORPUS_NO_VALUE_KNOWN_AT_DECISION")
    return max(
        eligible,
        key=lambda item: (item.observation_date, item.known_at, item.row_id),
    )


def _require_aware(value: datetime, code: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelTrainingError(f"{code}_MUST_BE_AWARE")


def _sha(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FredMacroFeatureCorpus",
    "FredMacroFeatureSpec",
    "build_fred_macro_feature_corpus",
]
