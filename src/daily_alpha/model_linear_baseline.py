"""Dependency-free interpretable linear baseline for research-only model training."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from .model_fit_protocol import FittedModelArtifact, ModelFamily, ModelSpecification
from .model_training import (
    DatasetPartition,
    ModelTrainingError,
    TrainingDatasetSnapshot,
    TrainingExample,
    WalkForwardFold,
)

RIDGE_ALPHA_KEY = "ridge_alpha"


@dataclass(frozen=True, slots=True)
class LinearBaselineModel:
    dataset_id: str
    fold_id: str
    specification_id: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float

    def __post_init__(self) -> None:
        if not self.dataset_id.strip():
            raise ModelTrainingError("LINEAR_MODEL_DATASET_ID_REQUIRED")
        if not self.fold_id.strip():
            raise ModelTrainingError("LINEAR_MODEL_FOLD_ID_REQUIRED")
        if not self.specification_id.strip():
            raise ModelTrainingError("LINEAR_MODEL_SPECIFICATION_ID_REQUIRED")
        width = len(self.feature_names)
        if width < 1:
            raise ModelTrainingError("LINEAR_MODEL_FEATURES_REQUIRED")
        if not (
            len(self.feature_means)
            == len(self.feature_scales)
            == len(self.coefficients)
            == width
        ):
            raise ModelTrainingError("LINEAR_MODEL_VECTOR_LENGTH_MISMATCH")
        if len(set(self.feature_names)) != width:
            raise ModelTrainingError("LINEAR_MODEL_FEATURES_MUST_BE_UNIQUE")
        values = (
            *self.feature_means,
            *self.feature_scales,
            *self.coefficients,
            self.intercept,
        )
        if any(not math.isfinite(float(value)) for value in values):
            raise ModelTrainingError("LINEAR_MODEL_VALUES_MUST_BE_FINITE")
        if any(scale <= 0 for scale in self.feature_scales):
            raise ModelTrainingError("LINEAR_MODEL_SCALE_MUST_BE_POSITIVE")

    @property
    def artifact_bytes(self) -> bytes:
        payload = {
            "dataset_id": self.dataset_id,
            "fold_id": self.fold_id,
            "specification_id": self.specification_id,
            "feature_names": self.feature_names,
            "feature_means": self.feature_means,
            "feature_scales": self.feature_scales,
            "coefficients": self.coefficients,
            "intercept": self.intercept,
        }
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()

    @property
    def artifact_sha256(self) -> str:
        return hashlib.sha256(self.artifact_bytes).hexdigest()

    def predict(self, example: TrainingExample) -> float:
        values = dict(example.features)
        missing = tuple(name for name in self.feature_names if name not in values)
        if missing:
            raise ModelTrainingError(f"LINEAR_MODEL_MISSING_FEATURES:{','.join(missing)}")
        prediction = self.intercept
        for index, name in enumerate(self.feature_names):
            standardized = (values[name] - self.feature_means[index]) / self.feature_scales[index]
            prediction += self.coefficients[index] * standardized
        if not math.isfinite(prediction):
            raise ModelTrainingError("LINEAR_MODEL_PREDICTION_MUST_BE_FINITE")
        return prediction


@dataclass(frozen=True, slots=True)
class LinearBaselineFit:
    model: LinearBaselineModel
    artifact: FittedModelArtifact

    def __post_init__(self) -> None:
        if self.model.dataset_id != self.artifact.dataset_id:
            raise ModelTrainingError("LINEAR_FIT_DATASET_LINEAGE_MISMATCH")
        if self.model.fold_id != self.artifact.fold_id:
            raise ModelTrainingError("LINEAR_FIT_FOLD_LINEAGE_MISMATCH")
        if self.model.specification_id != self.artifact.specification_id:
            raise ModelTrainingError("LINEAR_FIT_SPECIFICATION_LINEAGE_MISMATCH")
        if self.model.artifact_sha256 != self.artifact.artifact_sha256:
            raise ModelTrainingError("LINEAR_FIT_ARTIFACT_HASH_MISMATCH")


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    sample_count: int
    mean_absolute_error: float
    root_mean_squared_error: float
    r_squared: float | None

    def __post_init__(self) -> None:
        if self.sample_count < 1:
            raise ModelTrainingError("REGRESSION_SAMPLE_COUNT_MUST_BE_POSITIVE")
        values = (self.mean_absolute_error, self.root_mean_squared_error)
        if any(not math.isfinite(float(value)) or value < 0 for value in values):
            raise ModelTrainingError("REGRESSION_ERROR_METRIC_INVALID")
        if self.r_squared is not None and not math.isfinite(float(self.r_squared)):
            raise ModelTrainingError("REGRESSION_R_SQUARED_MUST_BE_FINITE")


@dataclass(frozen=True, slots=True)
class RegressionEvaluation:
    dataset_id: str
    fold_id: str
    specification_id: str
    artifact_sha256: str
    partition: DatasetPartition
    example_ids: tuple[str, ...]
    metrics: RegressionMetrics
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.example_ids:
            raise ModelTrainingError("REGRESSION_EVALUATION_EXAMPLES_REQUIRED")
        if self.metrics.sample_count != len(self.example_ids):
            raise ModelTrainingError("REGRESSION_EVALUATION_SAMPLE_COUNT_MISMATCH")
        if any(
            (
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("REGRESSION_EVALUATION_CANNOT_AUTHORIZE_TRADING")


def fit_linear_baseline(
    *,
    dataset: TrainingDatasetSnapshot,
    fold: WalkForwardFold,
    specification: ModelSpecification,
    fitting_code_revision: str,
) -> LinearBaselineFit:
    """Fit a ridge-linear realized-R baseline using the exact TRAIN partition only."""
    if specification.family is not ModelFamily.LINEAR_SCORE:
        raise ModelTrainingError("LINEAR_BASELINE_REQUIRES_LINEAR_SCORE_FAMILY")
    if specification.feature_schema_version != dataset.feature_schema_version:
        raise ModelTrainingError("LINEAR_BASELINE_FEATURE_SCHEMA_MISMATCH")
    if not fitting_code_revision.strip():
        raise ModelTrainingError("FITTING_CODE_REVISION_REQUIRED")

    alpha = _ridge_alpha(specification)
    example_by_id = {example.example_id: example for example in dataset.examples}
    try:
        train_examples = tuple(example_by_id[example_id] for example_id in fold.train_example_ids)
    except KeyError as exc:
        raise ModelTrainingError("TRAIN_EXAMPLE_NOT_PRESENT_IN_DATASET") from exc

    if not train_examples:
        raise ModelTrainingError("TRAIN_PARTITION_EMPTY")
    feature_names = specification.feature_names
    rows = tuple(_feature_row(example, feature_names) for example in train_examples)
    targets = tuple(example.realized_r for example in train_examples)

    means = tuple(
        sum(row[column] for row in rows) / len(rows) for column in range(len(feature_names))
    )
    scales = tuple(
        _population_scale(rows, column=column, mean=means[column])
        for column in range(len(feature_names))
    )
    standardized = tuple(
        tuple(
            (row[column] - means[column]) / scales[column]
            for column in range(len(feature_names))
        )
        for row in rows
    )
    intercept = sum(targets) / len(targets)
    centered_targets = tuple(target - intercept for target in targets)
    coefficients = _solve_ridge(standardized, centered_targets, alpha=alpha)

    model = LinearBaselineModel(
        dataset_id=dataset.dataset_id,
        fold_id=fold.window.fold_id,
        specification_id=specification.specification_id,
        feature_names=feature_names,
        feature_means=means,
        feature_scales=scales,
        coefficients=coefficients,
        intercept=intercept,
    )
    artifact = FittedModelArtifact(
        dataset_id=dataset.dataset_id,
        fold_id=fold.window.fold_id,
        specification_id=specification.specification_id,
        train_example_ids=fold.train_example_ids,
        artifact_sha256=model.artifact_sha256,
        fitting_code_revision=fitting_code_revision,
    )
    artifact.assert_matches_fold(fold)
    return LinearBaselineFit(model=model, artifact=artifact)


def evaluate_linear_baseline(
    *,
    dataset: TrainingDatasetSnapshot,
    fold: WalkForwardFold,
    fitted: LinearBaselineFit,
    partition: DatasetPartition,
) -> RegressionEvaluation:
    """Evaluate a fixed fitted artifact on one exact walk-forward partition."""
    if fitted.model.dataset_id != dataset.dataset_id:
        raise ModelTrainingError("REGRESSION_EVALUATION_DATASET_MISMATCH")
    if fitted.model.fold_id != fold.window.fold_id:
        raise ModelTrainingError("REGRESSION_EVALUATION_FOLD_MISMATCH")
    fitted.artifact.assert_matches_fold(fold)

    if partition is DatasetPartition.TRAIN:
        example_ids = fold.train_example_ids
    elif partition is DatasetPartition.VALIDATION:
        example_ids = fold.validation_example_ids
    else:
        example_ids = fold.test_example_ids

    example_by_id = {example.example_id: example for example in dataset.examples}
    try:
        examples = tuple(example_by_id[example_id] for example_id in example_ids)
    except KeyError as exc:
        raise ModelTrainingError("EVALUATION_EXAMPLE_NOT_PRESENT_IN_DATASET") from exc

    predictions = tuple(fitted.model.predict(example) for example in examples)
    actuals = tuple(example.realized_r for example in examples)
    errors = tuple(
        prediction - actual
        for prediction, actual in zip(predictions, actuals, strict=True)
    )
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    actual_mean = sum(actuals) / len(actuals)
    total_sum_squares = sum((actual - actual_mean) ** 2 for actual in actuals)
    residual_sum_squares = sum(error * error for error in errors)
    r_squared = None if total_sum_squares == 0 else 1.0 - residual_sum_squares / total_sum_squares

    return RegressionEvaluation(
        dataset_id=dataset.dataset_id,
        fold_id=fold.window.fold_id,
        specification_id=fitted.model.specification_id,
        artifact_sha256=fitted.model.artifact_sha256,
        partition=partition,
        example_ids=example_ids,
        metrics=RegressionMetrics(
            sample_count=len(examples),
            mean_absolute_error=mae,
            root_mean_squared_error=rmse,
            r_squared=r_squared,
        ),
    )


def _ridge_alpha(specification: ModelSpecification) -> float:
    parameters = dict(specification.hyperparameters)
    raw = parameters.get(RIDGE_ALPHA_KEY)
    if raw is None:
        raise ModelTrainingError("LINEAR_BASELINE_RIDGE_ALPHA_REQUIRED")
    try:
        alpha = float(raw)
    except ValueError as exc:
        raise ModelTrainingError("LINEAR_BASELINE_RIDGE_ALPHA_INVALID") from exc
    if not math.isfinite(alpha) or alpha <= 0:
        raise ModelTrainingError("LINEAR_BASELINE_RIDGE_ALPHA_MUST_BE_POSITIVE")
    return alpha


def _feature_row(example: TrainingExample, feature_names: tuple[str, ...]) -> tuple[float, ...]:
    features = dict(example.features)
    missing = tuple(name for name in feature_names if name not in features)
    if missing:
        raise ModelTrainingError(f"LINEAR_BASELINE_MISSING_FEATURES:{','.join(missing)}")
    return tuple(features[name] for name in feature_names)


def _population_scale(
    rows: tuple[tuple[float, ...], ...],
    *,
    column: int,
    mean: float,
) -> float:
    variance = sum((row[column] - mean) ** 2 for row in rows) / len(rows)
    if variance <= 0:
        return 1.0
    return math.sqrt(variance)


def _solve_ridge(
    rows: tuple[tuple[float, ...], ...],
    targets: tuple[float, ...],
    *,
    alpha: float,
) -> tuple[float, ...]:
    width = len(rows[0])
    matrix = [
        [sum(row[i] * row[j] for row in rows) for j in range(width)]
        for i in range(width)
    ]
    vector = [
        sum(row[i] * target for row, target in zip(rows, targets, strict=True))
        for i in range(width)
    ]
    for index in range(width):
        matrix[index][index] += alpha
    return tuple(_gaussian_elimination(matrix, vector))


def _gaussian_elimination(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for pivot_index in range(size):
        pivot_row = max(
            range(pivot_index, size),
            key=lambda row: abs(augmented[row][pivot_index]),
        )
        pivot = augmented[pivot_row][pivot_index]
        if abs(pivot) < 1e-15:
            raise ModelTrainingError("LINEAR_BASELINE_SINGULAR_SYSTEM")
        augmented[pivot_index], augmented[pivot_row] = (
            augmented[pivot_row],
            augmented[pivot_index],
        )
        pivot = augmented[pivot_index][pivot_index]
        augmented[pivot_index] = [value / pivot for value in augmented[pivot_index]]
        for row_index in range(size):
            if row_index == pivot_index:
                continue
            factor = augmented[row_index][pivot_index]
            if factor == 0:
                continue
            augmented[row_index] = [
                value - factor * pivot_value
                for value, pivot_value in zip(
                    augmented[row_index], augmented[pivot_index], strict=True
                )
            ]
    solution = [augmented[index][-1] for index in range(size)]
    if any(not math.isfinite(value) for value in solution):
        raise ModelTrainingError("LINEAR_BASELINE_COEFFICIENTS_MUST_BE_FINITE")
    return solution


__all__ = [
    "RIDGE_ALPHA_KEY",
    "LinearBaselineFit",
    "LinearBaselineModel",
    "RegressionEvaluation",
    "RegressionMetrics",
    "evaluate_linear_baseline",
    "fit_linear_baseline",
]
