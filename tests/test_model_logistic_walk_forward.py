import datetime as dt

import pytest

import daily_alpha.model_fit_protocol as fp
import daily_alpha.model_logistic_baseline as logistic
import daily_alpha.model_logistic_walk_forward as lwf
import daily_alpha.model_training as mt

BASE = dt.datetime(2025, 1, 2, 21, 0, tzinfo=dt.UTC)


def _example(symbol: str, day: int, x: float, realized_r: float) -> mt.TrainingExample:
    decision_at = BASE + dt.timedelta(days=day)
    return mt.TrainingExample(
        security_id=symbol,
        decision_at=decision_at,
        feature_known_at=decision_at,
        label_known_at=decision_at + dt.timedelta(days=3),
        label_horizon_days=3,
        features=(("x", x),),
        realized_r=realized_r,
        evidence_ids=(f"pit-{symbol}-{day}",),
    )


def _dataset(*, test_shift: float = 0.0) -> mt.TrainingDatasetSnapshot:
    return mt.TrainingDatasetSnapshot(
        as_of=BASE + dt.timedelta(days=40),
        feature_schema_version="LOGISTIC_WF_FEATURES_V1",
        label_definition="3D_REALIZED_R",
        examples=(
            _example("T0", 1, -2.0, -2.0),
            _example("T1", 2, -1.0, -1.0),
            _example("T2", 3, 1.0, 1.0),
            _example("T3", 4, 2.0, 2.0),
            _example("V_NEG", 10, -3.0, -2.0),
            _example("V_POS", 11, 3.0, 3.0),
            _example("X_NEG", 20, -4.0, -3.0 - test_shift),
            _example("X_POS", 21, 4.0, 4.0 + test_shift),
        ),
        source_revisions=("pit-bars-v1", "pit-features-v1", "pit-labels-v1"),
    )


def _fold(dataset: mt.TrainingDatasetSnapshot) -> mt.WalkForwardFold:
    return mt.build_walk_forward_fold(
        dataset,
        mt.WalkForwardWindow(
            fold_id="LOGISTIC-WF-1",
            train_start=BASE,
            train_end=BASE + dt.timedelta(days=5),
            validation_start=BASE + dt.timedelta(days=10),
            validation_end=BASE + dt.timedelta(days=12),
            test_start=BASE + dt.timedelta(days=20),
            test_end=BASE + dt.timedelta(days=22),
        ),
    )


def _spec(candidate_id: str, threshold: str) -> fp.ModelSpecification:
    return fp.ModelSpecification(
        candidate_id=candidate_id,
        family=fp.ModelFamily.LOGISTIC_CLASSIFIER,
        feature_schema_version="LOGISTIC_WF_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (logistic.LOGISTIC_L2_KEY, "1.0"),
            (logistic.LOGISTIC_ITERATIONS_KEY, "12"),
            (lwf.SIGNAL_PROBABILITY_THRESHOLD_KEY, threshold),
        ),
        random_seed=0,
    )


def test_complete_logistic_walk_forward_selects_on_validation_then_tests_fixed_winner() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    always_long = _spec("LOGISTIC-ALWAYS-LONG", "0")
    selective = _spec("LOGISTIC-SELECTIVE", "0.5")

    result = lwf.run_logistic_walk_forward_challenger(
        dataset=dataset,
        fold=fold,
        specifications=(always_long, selective),
        fitting_code_revision="logistic-wf-v1",
    )

    assert result.selection.selected_specification_id == selective.specification_id
    assert result.selection.test_metrics_observed is False
    assert result.final_test.selected_specification_id == selective.specification_id
    assert result.final_test.test_example_ids == fold.test_example_ids
    assert result.selected_candidate.fitted.artifact.train_example_ids == fold.train_example_ids
    assert result.promotion_authorized is False
    assert result.paper_mutation_authorized is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_test_labels_cannot_change_logistic_fit_or_validation_selection() -> None:
    first_dataset = _dataset(test_shift=0.0)
    altered_test_dataset = _dataset(test_shift=1000.0)
    specifications = (
        _spec("LOGISTIC-ALWAYS-LONG", "0"),
        _spec("LOGISTIC-SELECTIVE", "0.5"),
    )

    first = lwf.run_logistic_walk_forward_challenger(
        dataset=first_dataset,
        fold=_fold(first_dataset),
        specifications=specifications,
        fitting_code_revision="logistic-wf-v1",
    )
    altered = lwf.run_logistic_walk_forward_challenger(
        dataset=altered_test_dataset,
        fold=_fold(altered_test_dataset),
        specifications=specifications,
        fitting_code_revision="logistic-wf-v1",
    )

    assert first.selection.selected_specification_id == altered.selection.selected_specification_id
    assert (
        first.selected_candidate.fitted.model.coefficients
        == altered.selected_candidate.fitted.model.coefficients
    )
    assert (
        first.selected_candidate.fitted.model.intercept
        == altered.selected_candidate.fitted.model.intercept
    )
    assert first.final_test.metrics != altered.final_test.metrics
    assert first_dataset.dataset_id != altered_test_dataset.dataset_id


def test_each_logistic_validation_trial_uses_exact_oos_partition() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    result = lwf.run_logistic_walk_forward_challenger(
        dataset=dataset,
        fold=fold,
        specifications=(
            _spec("LOGISTIC-A", "0.25"),
            _spec("LOGISTIC-B", "0.5"),
            _spec("LOGISTIC-C", "0.75"),
        ),
        fitting_code_revision="logistic-wf-v1",
    )

    for candidate in result.candidates:
        assert candidate.validation_trial.validation_example_ids == fold.validation_example_ids
        assert candidate.fitted.artifact.train_example_ids == fold.train_example_ids
        assert candidate.fitted.artifact.validation_used_for_fitting is False
        assert candidate.fitted.artifact.test_used_for_fitting is False


def test_probability_threshold_must_be_explicit_and_bounded() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    missing = fp.ModelSpecification(
        candidate_id="LOGISTIC-MISSING-THRESHOLD",
        family=fp.ModelFamily.LOGISTIC_CLASSIFIER,
        feature_schema_version="LOGISTIC_WF_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (logistic.LOGISTIC_L2_KEY, "1.0"),
            (logistic.LOGISTIC_ITERATIONS_KEY, "12"),
        ),
        random_seed=0,
    )

    with pytest.raises(
        mt.ModelTrainingError,
        match="LOGISTIC_SIGNAL_PROBABILITY_THRESHOLD_REQUIRED",
    ):
        lwf.run_logistic_walk_forward_challenger(
            dataset=dataset,
            fold=fold,
            specifications=(missing,),
            fitting_code_revision="logistic-wf-v1",
        )

    out_of_range = _spec("LOGISTIC-OUT-OF-RANGE", "1.1")
    with pytest.raises(
        mt.ModelTrainingError,
        match="LOGISTIC_SIGNAL_PROBABILITY_THRESHOLD_OUT_OF_RANGE",
    ):
        lwf.run_logistic_walk_forward_challenger(
            dataset=dataset,
            fold=fold,
            specifications=(out_of_range,),
            fitting_code_revision="logistic-wf-v1",
        )


def test_non_logistic_family_cannot_enter_logistic_walk_forward() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    wrong_family = fp.ModelSpecification(
        candidate_id="TREE",
        family=fp.ModelFamily.TREE_ENSEMBLE,
        feature_schema_version="LOGISTIC_WF_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (logistic.LOGISTIC_L2_KEY, "1.0"),
            (logistic.LOGISTIC_ITERATIONS_KEY, "12"),
            (lwf.SIGNAL_PROBABILITY_THRESHOLD_KEY, "0.5"),
        ),
        random_seed=0,
    )

    with pytest.raises(
        mt.ModelTrainingError,
        match="LOGISTIC_WALK_FORWARD_REQUIRES_LOGISTIC_CLASSIFIER_FAMILY",
    ):
        lwf.run_logistic_walk_forward_challenger(
            dataset=dataset,
            fold=fold,
            specifications=(wrong_family,),
            fitting_code_revision="logistic-wf-v1",
        )
