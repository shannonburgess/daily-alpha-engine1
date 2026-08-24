"""Research-only logistic challenger: TRAIN fit -> VALIDATION select -> untouched TEST."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model_fit_protocol import (
    FinalTestEvaluation,
    ModelFamily,
    ModelSpecification,
    SelectionMetric,
    ValidationSelection,
    ValidationTrial,
    build_final_test_evaluation,
    select_validation_trial,
)
from .model_logistic_baseline import LogisticBaselineFit, fit_logistic_baseline
from .model_training import (
    ModelTrainingError,
    TrainingDatasetSnapshot,
    TrainingExample,
    WalkForwardFold,
    evaluate_oos_realized_r,
)

SIGNAL_PROBABILITY_THRESHOLD_KEY = "signal_probability_threshold"


@dataclass(frozen=True, slots=True)
class LogisticWalkForwardCandidate:
    specification: ModelSpecification
    fitted: LogisticBaselineFit
    validation_trial: ValidationTrial

    def __post_init__(self) -> None:
        if self.specification.specification_id != self.fitted.model.specification_id:
            raise ModelTrainingError("LOGISTIC_CANDIDATE_SPECIFICATION_FIT_MISMATCH")
        if self.validation_trial.artifact != self.fitted.artifact:
            raise ModelTrainingError("LOGISTIC_CANDIDATE_VALIDATION_ARTIFACT_MISMATCH")


@dataclass(frozen=True, slots=True)
class LogisticWalkForwardResult:
    dataset_id: str
    fold_id: str
    candidates: tuple[LogisticWalkForwardCandidate, ...]
    selection: ValidationSelection
    final_test: FinalTestEvaluation
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ModelTrainingError("LOGISTIC_WALK_FORWARD_CANDIDATES_REQUIRED")
        if self.selection.dataset_id != self.dataset_id:
            raise ModelTrainingError("LOGISTIC_SELECTION_DATASET_MISMATCH")
        if self.selection.fold_id != self.fold_id:
            raise ModelTrainingError("LOGISTIC_SELECTION_FOLD_MISMATCH")
        if self.final_test.dataset_id != self.dataset_id:
            raise ModelTrainingError("LOGISTIC_FINAL_TEST_DATASET_MISMATCH")
        if self.final_test.fold_id != self.fold_id:
            raise ModelTrainingError("LOGISTIC_FINAL_TEST_FOLD_MISMATCH")
        candidate_spec_ids = {item.specification.specification_id for item in self.candidates}
        if self.selection.selected_specification_id not in candidate_spec_ids:
            raise ModelTrainingError("LOGISTIC_SELECTED_SPECIFICATION_NOT_FIT")
        if any(
            (
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("LOGISTIC_WALK_FORWARD_CANNOT_AUTHORIZE_TRADING")

    @property
    def selected_candidate(self) -> LogisticWalkForwardCandidate:
        return next(
            candidate
            for candidate in self.candidates
            if candidate.specification.specification_id
            == self.selection.selected_specification_id
        )


def run_logistic_walk_forward_challenger(
    *,
    dataset: TrainingDatasetSnapshot,
    fold: WalkForwardFold,
    specifications: tuple[ModelSpecification, ...],
    fitting_code_revision: str,
    selection_metric: SelectionMetric = SelectionMetric.EXPECTANCY_R,
) -> LogisticWalkForwardResult:
    """Run a complete leak-proof logistic challenger over one frozen walk-forward fold."""
    if not specifications:
        raise ModelTrainingError("LOGISTIC_SPECIFICATIONS_REQUIRED")
    if len({item.specification_id for item in specifications}) != len(specifications):
        raise ModelTrainingError("LOGISTIC_SPECIFICATIONS_MUST_BE_UNIQUE")

    validation_examples = _examples_for_ids(dataset, fold.validation_example_ids)
    candidates: list[LogisticWalkForwardCandidate] = []
    for specification in specifications:
        if specification.family is not ModelFamily.LOGISTIC_CLASSIFIER:
            raise ModelTrainingError(
                "LOGISTIC_WALK_FORWARD_REQUIRES_LOGISTIC_CLASSIFIER_FAMILY"
            )
        threshold = _signal_probability_threshold(specification)
        fitted = fit_logistic_baseline(
            dataset=dataset,
            fold=fold,
            specification=specification,
            fitting_code_revision=fitting_code_revision,
        )
        validation_strategy_r = _strategy_realized_r(
            fitted=fitted,
            examples=validation_examples,
            threshold=threshold,
        )
        trial = ValidationTrial(
            artifact=fitted.artifact,
            validation_example_ids=fold.validation_example_ids,
            metrics=evaluate_oos_realized_r(validation_strategy_r),
        )
        trial.assert_matches_fold(fold)
        candidates.append(
            LogisticWalkForwardCandidate(
                specification=specification,
                fitted=fitted,
                validation_trial=trial,
            )
        )

    selection = select_validation_trial(
        dataset_id=dataset.dataset_id,
        fold=fold,
        trials=tuple(item.validation_trial for item in candidates),
        metric=selection_metric,
    )
    selected = next(
        candidate
        for candidate in candidates
        if candidate.specification.specification_id == selection.selected_specification_id
    )

    test_examples = _examples_for_ids(dataset, fold.test_example_ids)
    test_strategy_r = _strategy_realized_r(
        fitted=selected.fitted,
        examples=test_examples,
        threshold=_signal_probability_threshold(selected.specification),
    )
    final_test = build_final_test_evaluation(
        dataset_id=dataset.dataset_id,
        fold=fold,
        selection=selection,
        test_example_ids=fold.test_example_ids,
        metrics=evaluate_oos_realized_r(test_strategy_r),
    )

    return LogisticWalkForwardResult(
        dataset_id=dataset.dataset_id,
        fold_id=fold.window.fold_id,
        candidates=tuple(candidates),
        selection=selection,
        final_test=final_test,
    )


def _signal_probability_threshold(specification: ModelSpecification) -> float:
    parameters = dict(specification.hyperparameters)
    raw = parameters.get(SIGNAL_PROBABILITY_THRESHOLD_KEY)
    if raw is None:
        raise ModelTrainingError("LOGISTIC_SIGNAL_PROBABILITY_THRESHOLD_REQUIRED")
    try:
        threshold = float(raw)
    except ValueError as exc:
        raise ModelTrainingError("LOGISTIC_SIGNAL_PROBABILITY_THRESHOLD_INVALID") from exc
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ModelTrainingError("LOGISTIC_SIGNAL_PROBABILITY_THRESHOLD_OUT_OF_RANGE")
    return threshold


def _examples_for_ids(
    dataset: TrainingDatasetSnapshot,
    example_ids: tuple[str, ...],
) -> tuple[TrainingExample, ...]:
    by_id = {example.example_id: example for example in dataset.examples}
    try:
        return tuple(by_id[example_id] for example_id in example_ids)
    except KeyError as exc:
        raise ModelTrainingError("WALK_FORWARD_EXAMPLE_NOT_PRESENT_IN_DATASET") from exc


def _strategy_realized_r(
    *,
    fitted: LogisticBaselineFit,
    examples: tuple[TrainingExample, ...],
    threshold: float,
) -> tuple[float, ...]:
    if not examples:
        raise ModelTrainingError("WALK_FORWARD_EVALUATION_EXAMPLES_REQUIRED")
    return tuple(
        example.realized_r
        if fitted.model.predict_probability(example) > threshold
        else 0.0
        for example in examples
    )


__all__ = [
    "SIGNAL_PROBABILITY_THRESHOLD_KEY",
    "LogisticWalkForwardCandidate",
    "LogisticWalkForwardResult",
    "run_logistic_walk_forward_challenger",
]
