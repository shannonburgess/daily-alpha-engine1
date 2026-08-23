from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Mapping


class ModelTrainingError(ValueError):
    """Training evidence violates point-in-time or research-only constraints."""


class DatasetPartition(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


@dataclass(frozen=True, slots=True)
class TrainingExample:
    security_id: str
    decision_at: datetime
    feature_known_at: datetime
    label_known_at: datetime
    label_horizon_days: int
    features: tuple[tuple[str, float], ...]
    realized_r: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        if not security_id:
            raise ModelTrainingError("SECURITY_ID_REQUIRED")
        _require_aware(self.decision_at, "DECISION_AT")
        _require_aware(self.feature_known_at, "FEATURE_KNOWN_AT")
        _require_aware(self.label_known_at, "LABEL_KNOWN_AT")
        if self.feature_known_at > self.decision_at:
            raise ModelTrainingError("FEATURE_KNOWN_AFTER_DECISION")
        if self.label_known_at <= self.decision_at:
            raise ModelTrainingError("LABEL_MUST_MATURE_AFTER_DECISION")
        if self.label_horizon_days < 1:
            raise ModelTrainingError("LABEL_HORIZON_DAYS_MUST_BE_POSITIVE")
        if not isfinite(float(self.realized_r)):
            raise ModelTrainingError("REALIZED_R_MUST_BE_FINITE")
        if not self.features:
            raise ModelTrainingError("FEATURES_REQUIRED")

        normalized_features: list[tuple[str, float]] = []
        feature_names: set[str] = set()
        for name, value in self.features:
            normalized_name = str(name).strip()
            if not normalized_name:
                raise ModelTrainingError("FEATURE_NAME_REQUIRED")
            if normalized_name in feature_names:
                raise ModelTrainingError("DUPLICATE_FEATURE_NAME")
            numeric_value = float(value)
            if not isfinite(numeric_value):
                raise ModelTrainingError("FEATURE_VALUE_MUST_BE_FINITE")
            feature_names.add(normalized_name)
            normalized_features.append((normalized_name, numeric_value))

        normalized_evidence = tuple(sorted({item.strip() for item in self.evidence_ids if item.strip()}))
        if not normalized_evidence:
            raise ModelTrainingError("EVIDENCE_IDS_REQUIRED")

        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "features", tuple(sorted(normalized_features)))
        object.__setattr__(self, "evidence_ids", normalized_evidence)

    @property
    def example_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "decision_at": self.decision_at.isoformat(),
            "feature_known_at": self.feature_known_at.isoformat(),
            "label_known_at": self.label_known_at.isoformat(),
            "label_horizon_days": self.label_horizon_days,
            "features": self.features,
            "realized_r": self.realized_r,
            "evidence_ids": self.evidence_ids,
        }
        return _sha(payload)


@dataclass(frozen=True, slots=True)
class TrainingDatasetSnapshot:
    as_of: datetime
    feature_schema_version: str
    label_definition: str
    examples: tuple[TrainingExample, ...]
    source_revisions: tuple[str, ...]
    training_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "DATASET_AS_OF")
        if not self.feature_schema_version.strip():
            raise ModelTrainingError("FEATURE_SCHEMA_VERSION_REQUIRED")
        if not self.label_definition.strip():
            raise ModelTrainingError("LABEL_DEFINITION_REQUIRED")
        if not self.examples:
            raise ModelTrainingError("DATASET_EXAMPLES_REQUIRED")
        if any(
            (
                self.training_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("DATASET_CANNOT_GRANT_EXECUTION_AUTHORITY")

        seen_keys: set[tuple[str, datetime]] = set()
        seen_ids: set[str] = set()
        for example in self.examples:
            if example.label_known_at > self.as_of:
                raise ModelTrainingError("LABEL_NOT_MATURE_BY_DATASET_AS_OF")
            key = (example.security_id, example.decision_at)
            if key in seen_keys:
                raise ModelTrainingError("DUPLICATE_SECURITY_DECISION_EXAMPLE")
            if example.example_id in seen_ids:
                raise ModelTrainingError("DUPLICATE_EXAMPLE_ID")
            seen_keys.add(key)
            seen_ids.add(example.example_id)

        normalized_sources = tuple(sorted({item.strip() for item in self.source_revisions if item.strip()}))
        if not normalized_sources:
            raise ModelTrainingError("SOURCE_REVISIONS_REQUIRED")
        object.__setattr__(self, "examples", tuple(sorted(self.examples, key=lambda item: (item.decision_at, item.security_id))))
        object.__setattr__(self, "source_revisions", normalized_sources)

    @property
    def dataset_id(self) -> str:
        payload = {
            "as_of": self.as_of.isoformat(),
            "feature_schema_version": self.feature_schema_version,
            "label_definition": self.label_definition,
            "example_ids": tuple(item.example_id for item in self.examples),
            "source_revisions": self.source_revisions,
        }
        return _sha(payload)


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    fold_id: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        if not self.fold_id.strip():
            raise ModelTrainingError("FOLD_ID_REQUIRED")
        for name, value in (
            ("TRAIN_START", self.train_start),
            ("TRAIN_END", self.train_end),
            ("VALIDATION_START", self.validation_start),
            ("VALIDATION_END", self.validation_end),
            ("TEST_START", self.test_start),
            ("TEST_END", self.test_end),
        ):
            _require_aware(value, name)
        if not (
            self.train_start <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ModelTrainingError("WALK_FORWARD_WINDOWS_MUST_BE_STRICTLY_CHRONOLOGICAL")

    def partition_for(self, decision_at: datetime) -> DatasetPartition | None:
        _require_aware(decision_at, "DECISION_AT")
        if self.train_start <= decision_at <= self.train_end:
            return DatasetPartition.TRAIN
        if self.validation_start <= decision_at <= self.validation_end:
            return DatasetPartition.VALIDATION
        if self.test_start <= decision_at <= self.test_end:
            return DatasetPartition.TEST
        return None


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    window: WalkForwardWindow
    train_example_ids: tuple[str, ...]
    validation_example_ids: tuple[str, ...]
    test_example_ids: tuple[str, ...]
    fitting_may_use_validation: bool = False
    fitting_may_use_test: bool = False

    def __post_init__(self) -> None:
        if self.fitting_may_use_validation or self.fitting_may_use_test:
            raise ModelTrainingError("OUT_OF_SAMPLE_DATA_CANNOT_BE_USED_FOR_FITTING")
        train = set(self.train_example_ids)
        validation = set(self.validation_example_ids)
        test = set(self.test_example_ids)
        if train & validation or train & test or validation & test:
            raise ModelTrainingError("WALK_FORWARD_PARTITIONS_OVERLAP")
        if not train:
            raise ModelTrainingError("TRAIN_PARTITION_EMPTY")
        if not validation:
            raise ModelTrainingError("VALIDATION_PARTITION_EMPTY")
        if not test:
            raise ModelTrainingError("TEST_PARTITION_EMPTY")


@dataclass(frozen=True, slots=True)
class OutOfSampleMetrics:
    sample_count: int
    hit_rate: float
    expectancy_r: float
    profit_factor: float | None
    cumulative_r: float
    max_drawdown_r: float

    def __post_init__(self) -> None:
        if self.sample_count < 1:
            raise ModelTrainingError("OOS_SAMPLE_COUNT_MUST_BE_POSITIVE")
        if not 0.0 <= self.hit_rate <= 1.0:
            raise ModelTrainingError("OOS_HIT_RATE_OUT_OF_RANGE")
        for name, value in (
            ("EXPECTANCY_R", self.expectancy_r),
            ("CUMULATIVE_R", self.cumulative_r),
            ("MAX_DRAWDOWN_R", self.max_drawdown_r),
        ):
            if not isfinite(float(value)):
                raise ModelTrainingError(f"OOS_{name}_MUST_BE_FINITE")
        if self.max_drawdown_r < 0:
            raise ModelTrainingError("OOS_MAX_DRAWDOWN_R_MUST_BE_NON_NEGATIVE")
        if self.profit_factor is not None and (
            not isfinite(float(self.profit_factor)) or self.profit_factor < 0
        ):
            raise ModelTrainingError("OOS_PROFIT_FACTOR_INVALID")


@dataclass(frozen=True, slots=True)
class ResearchModelCandidateAssessment:
    candidate_id: str
    dataset_id: str
    fold_id: str
    validation_metrics: OutOfSampleMetrics
    test_metrics: OutOfSampleMetrics
    tuning_notes: tuple[str, ...] = ()
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ModelTrainingError("CANDIDATE_ID_REQUIRED")
        if not self.dataset_id.strip():
            raise ModelTrainingError("DATASET_ID_REQUIRED")
        if not self.fold_id.strip():
            raise ModelTrainingError("FOLD_ID_REQUIRED")
        if any(
            (
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("RESEARCH_ASSESSMENT_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING")


def build_walk_forward_fold(
    dataset: TrainingDatasetSnapshot,
    window: WalkForwardWindow,
) -> WalkForwardFold:
    train: list[str] = []
    validation: list[str] = []
    test: list[str] = []
    for example in dataset.examples:
        partition = window.partition_for(example.decision_at)
        if partition is DatasetPartition.TRAIN:
            train.append(example.example_id)
        elif partition is DatasetPartition.VALIDATION:
            validation.append(example.example_id)
        elif partition is DatasetPartition.TEST:
            test.append(example.example_id)
    return WalkForwardFold(
        window=window,
        train_example_ids=tuple(train),
        validation_example_ids=tuple(validation),
        test_example_ids=tuple(test),
    )


def evaluate_oos_realized_r(realized_r: tuple[float, ...]) -> OutOfSampleMetrics:
    if not realized_r:
        raise ModelTrainingError("OOS_REALIZED_R_REQUIRED")
    values = tuple(float(value) for value in realized_r)
    if any(not isfinite(value) for value in values):
        raise ModelTrainingError("OOS_REALIZED_R_MUST_BE_FINITE")

    wins = tuple(value for value in values if value > 0)
    losses = tuple(value for value in values if value < 0)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = None if gross_loss == 0 else gross_profit / gross_loss

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return OutOfSampleMetrics(
        sample_count=len(values),
        hit_rate=len(wins) / len(values),
        expectancy_r=sum(values) / len(values),
        profit_factor=profit_factor,
        cumulative_r=sum(values),
        max_drawdown_r=max_drawdown,
    )


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelTrainingError(f"{field}_MUST_BE_TIMEZONE_AWARE")


def _sha(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DatasetPartition",
    "ModelTrainingError",
    "OutOfSampleMetrics",
    "ResearchModelCandidateAssessment",
    "TrainingDatasetSnapshot",
    "TrainingExample",
    "WalkForwardFold",
    "WalkForwardWindow",
    "build_walk_forward_fold",
    "evaluate_oos_realized_r",
]
