from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .model_training import ModelTrainingError, OutOfSampleMetrics, WalkForwardFold


class ModelFamily(StrEnum):
    LINEAR_SCORE = "LINEAR_SCORE"
    LOGISTIC_CLASSIFIER = "LOGISTIC_CLASSIFIER"
    TREE_ENSEMBLE = "TREE_ENSEMBLE"
    GRADIENT_BOOSTED_TREES = "GRADIENT_BOOSTED_TREES"
    OTHER = "OTHER"


class SelectionMetric(StrEnum):
    EXPECTANCY_R = "EXPECTANCY_R"
    PROFIT_FACTOR = "PROFIT_FACTOR"
    HIT_RATE = "HIT_RATE"


@dataclass(frozen=True, slots=True)
class ModelSpecification:
    candidate_id: str
    family: ModelFamily
    feature_schema_version: str
    feature_names: tuple[str, ...]
    hyperparameters: tuple[tuple[str, str], ...]
    random_seed: int

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ModelTrainingError("CANDIDATE_ID_REQUIRED")
        if not self.feature_schema_version.strip():
            raise ModelTrainingError("FEATURE_SCHEMA_VERSION_REQUIRED")
        normalized_features = tuple(sorted({name.strip() for name in self.feature_names if name.strip()}))
        if not normalized_features:
            raise ModelTrainingError("MODEL_FEATURES_REQUIRED")
        if len(normalized_features) != len(self.feature_names):
            raise ModelTrainingError("MODEL_FEATURES_MUST_BE_UNIQUE")
        normalized_hyperparameters: list[tuple[str, str]] = []
        names: set[str] = set()
        for raw_name, raw_value in self.hyperparameters:
            name = raw_name.strip()
            value = raw_value.strip()
            if not name or not value:
                raise ModelTrainingError("HYPERPARAMETER_NAME_AND_VALUE_REQUIRED")
            if name in names:
                raise ModelTrainingError("DUPLICATE_HYPERPARAMETER")
            names.add(name)
            normalized_hyperparameters.append((name, value))
        object.__setattr__(self, "feature_names", normalized_features)
        object.__setattr__(self, "hyperparameters", tuple(sorted(normalized_hyperparameters)))

    @property
    def specification_id(self) -> str:
        return _sha(
            {
                "candidate_id": self.candidate_id,
                "family": self.family.value,
                "feature_schema_version": self.feature_schema_version,
                "feature_names": self.feature_names,
                "hyperparameters": self.hyperparameters,
                "random_seed": self.random_seed,
            }
        )


@dataclass(frozen=True, slots=True)
class FittedModelArtifact:
    dataset_id: str
    fold_id: str
    specification_id: str
    train_example_ids: tuple[str, ...]
    artifact_sha256: str
    fitting_code_revision: str
    validation_used_for_fitting: bool = False
    test_used_for_fitting: bool = False
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        for value, error in (
            (self.dataset_id, "DATASET_ID_REQUIRED"),
            (self.fold_id, "FOLD_ID_REQUIRED"),
            (self.specification_id, "SPECIFICATION_ID_REQUIRED"),
            (self.fitting_code_revision, "FITTING_CODE_REVISION_REQUIRED"),
        ):
            if not value.strip():
                raise ModelTrainingError(error)
        if not self.train_example_ids:
            raise ModelTrainingError("FIT_TRAIN_EXAMPLE_IDS_REQUIRED")
        if len(set(self.train_example_ids)) != len(self.train_example_ids):
            raise ModelTrainingError("FIT_TRAIN_EXAMPLE_IDS_MUST_BE_UNIQUE")
        _require_sha256(self.artifact_sha256, "MODEL_ARTIFACT_SHA256")
        if self.validation_used_for_fitting or self.test_used_for_fitting:
            raise ModelTrainingError("OUT_OF_SAMPLE_DATA_USED_FOR_FITTING")
        if self.promotion_authorized or self.trading_authorized or self.live_trading_enabled:
            raise ModelTrainingError("FITTED_ARTIFACT_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING")

    def assert_matches_fold(self, fold: WalkForwardFold) -> None:
        if self.fold_id != fold.window.fold_id:
            raise ModelTrainingError("FIT_FOLD_ID_MISMATCH")
        if tuple(self.train_example_ids) != tuple(fold.train_example_ids):
            raise ModelTrainingError("FIT_MUST_USE_EXACT_TRAIN_PARTITION")


@dataclass(frozen=True, slots=True)
class ValidationTrial:
    artifact: FittedModelArtifact
    validation_example_ids: tuple[str, ...]
    metrics: OutOfSampleMetrics

    def assert_matches_fold(self, fold: WalkForwardFold) -> None:
        self.artifact.assert_matches_fold(fold)
        if tuple(self.validation_example_ids) != tuple(fold.validation_example_ids):
            raise ModelTrainingError("VALIDATION_MUST_USE_EXACT_VALIDATION_PARTITION")
        if set(self.validation_example_ids) & set(self.artifact.train_example_ids):
            raise ModelTrainingError("VALIDATION_OVERLAPS_TRAINING")
        if self.metrics.sample_count != len(self.validation_example_ids):
            raise ModelTrainingError("VALIDATION_METRIC_SAMPLE_COUNT_MISMATCH")


@dataclass(frozen=True, slots=True)
class ValidationSelection:
    dataset_id: str
    fold_id: str
    selection_metric: SelectionMetric
    selected_specification_id: str
    selected_artifact_sha256: str
    trial_specification_ids: tuple[str, ...]
    selection_value: float
    test_metrics_observed: bool = False
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.test_metrics_observed:
            raise ModelTrainingError("TEST_DATA_CANNOT_INFLUENCE_VALIDATION_SELECTION")
        if self.selected_specification_id not in self.trial_specification_ids:
            raise ModelTrainingError("SELECTED_SPECIFICATION_NOT_IN_VALIDATION_TRIALS")
        if not isfinite(float(self.selection_value)):
            raise ModelTrainingError("SELECTION_VALUE_MUST_BE_FINITE")
        _require_sha256(self.selected_artifact_sha256, "SELECTED_ARTIFACT_SHA256")
        if self.promotion_authorized or self.trading_authorized or self.live_trading_enabled:
            raise ModelTrainingError("VALIDATION_SELECTION_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING")


@dataclass(frozen=True, slots=True)
class FinalTestEvaluation:
    dataset_id: str
    fold_id: str
    selected_specification_id: str
    selected_artifact_sha256: str
    test_example_ids: tuple[str, ...]
    metrics: OutOfSampleMetrics
    selection: ValidationSelection
    retuned_after_test: bool = False
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.retuned_after_test:
            raise ModelTrainingError("MODEL_CANNOT_BE_RETUNED_AFTER_FINAL_TEST")
        if self.selection.dataset_id != self.dataset_id or self.selection.fold_id != self.fold_id:
            raise ModelTrainingError("FINAL_TEST_SELECTION_LINEAGE_MISMATCH")
        if self.selection.selected_specification_id != self.selected_specification_id:
            raise ModelTrainingError("FINAL_TEST_SPECIFICATION_MISMATCH")
        if self.selection.selected_artifact_sha256 != self.selected_artifact_sha256:
            raise ModelTrainingError("FINAL_TEST_ARTIFACT_MISMATCH")
        if self.metrics.sample_count != len(self.test_example_ids):
            raise ModelTrainingError("TEST_METRIC_SAMPLE_COUNT_MISMATCH")
        if self.promotion_authorized or self.trading_authorized or self.live_trading_enabled:
            raise ModelTrainingError("FINAL_TEST_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING")

    def assert_matches_fold(self, fold: WalkForwardFold) -> None:
        if self.fold_id != fold.window.fold_id:
            raise ModelTrainingError("FINAL_TEST_FOLD_ID_MISMATCH")
        if tuple(self.test_example_ids) != tuple(fold.test_example_ids):
            raise ModelTrainingError("FINAL_TEST_MUST_USE_EXACT_TEST_PARTITION")


def select_validation_trial(
    *,
    dataset_id: str,
    fold: WalkForwardFold,
    trials: tuple[ValidationTrial, ...],
    metric: SelectionMetric = SelectionMetric.EXPECTANCY_R,
) -> ValidationSelection:
    if not trials:
        raise ModelTrainingError("VALIDATION_TRIALS_REQUIRED")
    seen_specs: set[str] = set()
    for trial in trials:
        trial.assert_matches_fold(fold)
        if trial.artifact.dataset_id != dataset_id:
            raise ModelTrainingError("VALIDATION_DATASET_ID_MISMATCH")
        if trial.artifact.specification_id in seen_specs:
            raise ModelTrainingError("DUPLICATE_VALIDATION_SPECIFICATION")
        seen_specs.add(trial.artifact.specification_id)

    def score(trial: ValidationTrial) -> tuple[float, float, str]:
        metrics = trial.metrics
        if metric is SelectionMetric.EXPECTANCY_R:
            primary = metrics.expectancy_r
        elif metric is SelectionMetric.PROFIT_FACTOR:
            primary = -1.0 if metrics.profit_factor is None else metrics.profit_factor
        else:
            primary = metrics.hit_rate
        return primary, -metrics.max_drawdown_r, trial.artifact.specification_id

    selected = max(trials, key=score)
    selected_value = score(selected)[0]
    return ValidationSelection(
        dataset_id=dataset_id,
        fold_id=fold.window.fold_id,
        selection_metric=metric,
        selected_specification_id=selected.artifact.specification_id,
        selected_artifact_sha256=selected.artifact.artifact_sha256,
        trial_specification_ids=tuple(sorted(seen_specs)),
        selection_value=selected_value,
    )


def build_final_test_evaluation(
    *,
    dataset_id: str,
    fold: WalkForwardFold,
    selection: ValidationSelection,
    test_example_ids: tuple[str, ...],
    metrics: OutOfSampleMetrics,
) -> FinalTestEvaluation:
    if selection.dataset_id != dataset_id:
        raise ModelTrainingError("FINAL_TEST_DATASET_ID_MISMATCH")
    evaluation = FinalTestEvaluation(
        dataset_id=dataset_id,
        fold_id=fold.window.fold_id,
        selected_specification_id=selection.selected_specification_id,
        selected_artifact_sha256=selection.selected_artifact_sha256,
        test_example_ids=test_example_ids,
        metrics=metrics,
        selection=selection,
    )
    evaluation.assert_matches_fold(fold)
    return evaluation


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64:
        raise ModelTrainingError(f"{field}_INVALID")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ModelTrainingError(f"{field}_INVALID") from exc


def _sha(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FinalTestEvaluation",
    "FittedModelArtifact",
    "ModelFamily",
    "ModelSpecification",
    "SelectionMetric",
    "ValidationSelection",
    "ValidationTrial",
    "build_final_test_evaluation",
    "select_validation_trial",
]
