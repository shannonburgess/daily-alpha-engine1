"""Dependency-free interpretable logistic baseline for research-only model training."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from .model_fit_protocol import FittedModelArtifact, ModelFamily, ModelSpecification
from .model_training import (
    ModelTrainingError,
    TrainingDatasetSnapshot,
    TrainingExample,
    WalkForwardFold,
)

LOGISTIC_L2_KEY = "logistic_l2"
LOGISTIC_ITERATIONS_KEY = "logistic_iterations"
POSITIVE_CLASS_RULE = "REALIZED_R_GT_0"


@dataclass(frozen=True, slots=True)
class LogisticBaselineModel:
    dataset_id: str
    fold_id: str
    specification_id: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    l2_penalty: float
    iterations: int
    positive_class_rule: str = POSITIVE_CLASS_RULE

    def __post_init__(self) -> None:
        if not self.dataset_id.strip():
            raise ModelTrainingError("LOGISTIC_MODEL_DATASET_ID_REQUIRED")
        if not self.fold_id.strip():
            raise ModelTrainingError("LOGISTIC_MODEL_FOLD_ID_REQUIRED")
        if not self.specification_id.strip():
            raise ModelTrainingError("LOGISTIC_MODEL_SPECIFICATION_ID_REQUIRED")
        width = len(self.feature_names)
        if width < 1:
            raise ModelTrainingError("LOGISTIC_MODEL_FEATURES_REQUIRED")
        if not (
            len(self.feature_means)
            == len(self.feature_scales)
            == len(self.coefficients)
            == width
        ):
            raise ModelTrainingError("LOGISTIC_MODEL_VECTOR_LENGTH_MISMATCH")
        if len(set(self.feature_names)) != width:
            raise ModelTrainingError("LOGISTIC_MODEL_FEATURES_MUST_BE_UNIQUE")
        values = (
            *self.feature_means,
            *self.feature_scales,
            *self.coefficients,
            self.intercept,
            self.l2_penalty,
        )
        if any(not math.isfinite(float(value)) for value in values):
            raise ModelTrainingError("LOGISTIC_MODEL_VALUES_MUST_BE_FINITE")
        if any(scale <= 0 for scale in self.feature_scales):
            raise ModelTrainingError("LOGISTIC_MODEL_SCALE_MUST_BE_POSITIVE")
        if self.l2_penalty <= 0:
            raise ModelTrainingError("LOGISTIC_MODEL_L2_MUST_BE_POSITIVE")
        if self.iterations < 1:
            raise ModelTrainingError("LOGISTIC_MODEL_ITERATIONS_MUST_BE_POSITIVE")
        if self.positive_class_rule != POSITIVE_CLASS_RULE:
            raise ModelTrainingError("LOGISTIC_MODEL_POSITIVE_CLASS_RULE_MISMATCH")

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
            "l2_penalty": self.l2_penalty,
            "iterations": self.iterations,
            "positive_class_rule": self.positive_class_rule,
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

    def predict_probability(self, example: TrainingExample) -> float:
        values = dict(example.features)
        missing = tuple(name for name in self.feature_names if name not in values)
        if missing:
            raise ModelTrainingError(f"LOGISTIC_MODEL_MISSING_FEATURES:{','.join(missing)}")
        score = self.intercept
        for index, name in enumerate(self.feature_names):
            standardized = (values[name] - self.feature_means[index]) / self.feature_scales[index]
            score += self.coefficients[index] * standardized
        probability = _sigmoid(score)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ModelTrainingError("LOGISTIC_MODEL_PROBABILITY_INVALID")
        return probability


@dataclass(frozen=True, slots=True)
class LogisticBaselineFit:
    model: LogisticBaselineModel
    artifact: FittedModelArtifact

    def __post_init__(self) -> None:
        if self.model.dataset_id != self.artifact.dataset_id:
            raise ModelTrainingError("LOGISTIC_FIT_DATASET_LINEAGE_MISMATCH")
        if self.model.fold_id != self.artifact.fold_id:
            raise ModelTrainingError("LOGISTIC_FIT_FOLD_LINEAGE_MISMATCH")
        if self.model.specification_id != self.artifact.specification_id:
            raise ModelTrainingError("LOGISTIC_FIT_SPECIFICATION_LINEAGE_MISMATCH")
        if self.model.artifact_sha256 != self.artifact.artifact_sha256:
            raise ModelTrainingError("LOGISTIC_FIT_ARTIFACT_HASH_MISMATCH")


def fit_logistic_baseline(
    *,
    dataset: TrainingDatasetSnapshot,
    fold: WalkForwardFold,
    specification: ModelSpecification,
    fitting_code_revision: str,
) -> LogisticBaselineFit:
    """Fit an L2 logistic realized-R-sign baseline using the exact TRAIN partition only."""
    if specification.family is not ModelFamily.LOGISTIC_CLASSIFIER:
        raise ModelTrainingError("LOGISTIC_BASELINE_REQUIRES_LOGISTIC_CLASSIFIER_FAMILY")
    if specification.feature_schema_version != dataset.feature_schema_version:
        raise ModelTrainingError("LOGISTIC_BASELINE_FEATURE_SCHEMA_MISMATCH")
    if not fitting_code_revision.strip():
        raise ModelTrainingError("FITTING_CODE_REVISION_REQUIRED")

    l2_penalty = _logistic_l2(specification)
    iterations = _logistic_iterations(specification)
    example_by_id = {example.example_id: example for example in dataset.examples}
    try:
        train_examples = tuple(example_by_id[example_id] for example_id in fold.train_example_ids)
    except KeyError as exc:
        raise ModelTrainingError("TRAIN_EXAMPLE_NOT_PRESENT_IN_DATASET") from exc
    if not train_examples:
        raise ModelTrainingError("TRAIN_PARTITION_EMPTY")

    feature_names = specification.feature_names
    rows = tuple(_feature_row(example, feature_names) for example in train_examples)
    targets = tuple(1.0 if example.realized_r > 0 else 0.0 for example in train_examples)
    if len(set(targets)) < 2:
        raise ModelTrainingError("LOGISTIC_BASELINE_TRAIN_REQUIRES_BOTH_CLASSES")

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
    intercept, coefficients = _fit_newton(
        standardized,
        targets,
        l2_penalty=l2_penalty,
        iterations=iterations,
    )

    model = LogisticBaselineModel(
        dataset_id=dataset.dataset_id,
        fold_id=fold.window.fold_id,
        specification_id=specification.specification_id,
        feature_names=feature_names,
        feature_means=means,
        feature_scales=scales,
        coefficients=coefficients,
        intercept=intercept,
        l2_penalty=l2_penalty,
        iterations=iterations,
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
    return LogisticBaselineFit(model=model, artifact=artifact)


def _logistic_l2(specification: ModelSpecification) -> float:
    parameters = dict(specification.hyperparameters)
    raw = parameters.get(LOGISTIC_L2_KEY)
    if raw is None:
        raise ModelTrainingError("LOGISTIC_BASELINE_L2_REQUIRED")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ModelTrainingError("LOGISTIC_BASELINE_L2_INVALID") from exc
    if not math.isfinite(value) or value <= 0:
        raise ModelTrainingError("LOGISTIC_BASELINE_L2_MUST_BE_POSITIVE")
    return value


def _logistic_iterations(specification: ModelSpecification) -> int:
    parameters = dict(specification.hyperparameters)
    raw = parameters.get(LOGISTIC_ITERATIONS_KEY)
    if raw is None:
        raise ModelTrainingError("LOGISTIC_BASELINE_ITERATIONS_REQUIRED")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ModelTrainingError("LOGISTIC_BASELINE_ITERATIONS_INVALID") from exc
    if str(value) != raw or not 1 <= value <= 100:
        raise ModelTrainingError("LOGISTIC_BASELINE_ITERATIONS_OUT_OF_RANGE")
    return value


def _feature_row(example: TrainingExample, feature_names: tuple[str, ...]) -> tuple[float, ...]:
    features = dict(example.features)
    missing = tuple(name for name in feature_names if name not in features)
    if missing:
        raise ModelTrainingError(f"LOGISTIC_BASELINE_MISSING_FEATURES:{','.join(missing)}")
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


def _fit_newton(
    rows: tuple[tuple[float, ...], ...],
    targets: tuple[float, ...],
    *,
    l2_penalty: float,
    iterations: int,
) -> tuple[float, tuple[float, ...]]:
    width = len(rows[0])
    positive_rate = sum(targets) / len(targets)
    intercept = math.log(positive_rate / (1.0 - positive_rate))
    coefficients = [0.0 for _ in range(width)]

    for _ in range(iterations):
        probabilities = tuple(
            _sigmoid(intercept + sum(coef * value for coef, value in zip(coefficients, row)))
            for row in rows
        )
        weights = tuple(max(probability * (1.0 - probability), 1e-12) for probability in probabilities)
        design = tuple((1.0, *row) for row in rows)
        gradient = [0.0 for _ in range(width + 1)]
        hessian = [[0.0 for _ in range(width + 1)] for _ in range(width + 1)]

        for vector, target, probability, weight in zip(
            design, targets, probabilities, weights, strict=True
        ):
            residual = target - probability
            for i in range(width + 1):
                gradient[i] += vector[i] * residual
                for j in range(width + 1):
                    hessian[i][j] += weight * vector[i] * vector[j]

        for index, coefficient in enumerate(coefficients, start=1):
            gradient[index] -= l2_penalty * coefficient
            hessian[index][index] += l2_penalty

        delta = _gaussian_elimination(hessian, gradient)
        intercept += delta[0]
        coefficients = [
            coefficient + delta[index + 1]
            for index, coefficient in enumerate(coefficients)
        ]
        if any(not math.isfinite(value) for value in (intercept, *coefficients)):
            raise ModelTrainingError("LOGISTIC_BASELINE_COEFFICIENTS_MUST_BE_FINITE")

    return intercept, tuple(coefficients)


def _sigmoid(value: float) -> float:
    if value >= 0:
        decay = math.exp(-value)
        return 1.0 / (1.0 + decay)
    growth = math.exp(value)
    return growth / (1.0 + growth)


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
            raise ModelTrainingError("LOGISTIC_BASELINE_SINGULAR_SYSTEM")
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
        raise ModelTrainingError("LOGISTIC_BASELINE_NEWTON_STEP_MUST_BE_FINITE")
    return solution


__all__ = [
    "LOGISTIC_ITERATIONS_KEY",
    "LOGISTIC_L2_KEY",
    "POSITIVE_CLASS_RULE",
    "LogisticBaselineFit",
    "LogisticBaselineModel",
    "fit_logistic_baseline",
]
