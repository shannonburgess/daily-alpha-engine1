import datetime as dt

import pytest

import daily_alpha.model_fit_protocol as fp
import daily_alpha.model_linear_baseline as lb
import daily_alpha.model_ridge_walk_forward as rw
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
        feature_schema_version="RIDGE_WF_FEATURES_V1",
        label_definition="3D_REALIZED_R",
        examples=(
            _example("T0", 1, 0.0, -1.0),
            _example("T1", 2, 1.0, 0.0),
            _example("T2", 3, 2.0, 1.0),
            _example("T3", 4, 3.0, 2.0),
            _example("V_POS", 10, 4.0, 3.0),
            _example("V_NEG", 11, -1.0, -2.0),
            _example("X_POS", 20, 5.0, 4.0 + test_shift),
            _example("X_NEG", 21, -2.0, -3.0 - test_shift),
        ),
        source_revisions=("pit-bars-v1", "pit-features-v1", "pit-labels-v1"),
    )


def _fold(dataset: mt.TrainingDatasetSnapshot) -> mt.WalkForwardFold:
    return mt.build_walk_forward_fold(
        dataset,
        mt.WalkForwardWindow(
            fold_id="RIDGE-WF-1",
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
        family=fp.ModelFamily.LINEAR_SCORE,
        feature_schema_version="RIDGE_WF_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (lb.RIDGE_ALPHA_KEY, "0.1"),
            (rw.SIGNAL_THRESHOLD_KEY, threshold),
        ),
        random_seed=0,
    )


def test_complete_walk_forward_fits_train_selects_validation_and_tests_fixed_winner() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    selective = _spec("RIDGE-SELECTIVE", "0")
    always_long = _spec("RIDGE-ALWAYS-LONG", "-999")

    result = rw.run_ridge_walk_forward_challenger(
        dataset=dataset,
        fold=fold,
        specifications=(always_long, selective),
        fitting_code_revision="ridge-wf-v1",
    )

    assert result.selection.selected_specification_id == selective.specification_id
    assert result.selection.test_metrics_observed is False
    assert result.final_test.selected_specification_id == selective.specification_id
    assert result.final_test.test_example_ids == fold.test_example_ids
    assert result.final_test.metrics.sample_count == len(fold.test_example_ids)
    assert result.selected_candidate.fitted.artifact.train_example_ids == fold.train_example_ids
    assert result.promotion_authorized is False
    assert result.paper_mutation_authorized is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_test_labels_cannot_change_fit_or_validation_selected_specification() -> None:
    first_dataset = _dataset(test_shift=0.0)
    altered_test_dataset = _dataset(test_shift=1000.0)
    specifications = (
        _spec("RIDGE-ALWAYS-LONG", "-999"),
        _spec("RIDGE-SELECTIVE", "0"),
    )

    first = rw.run_ridge_walk_forward_challenger(
        dataset=first_dataset,
        fold=_fold(first_dataset),
        specifications=specifications,
        fitting_code_revision="ridge-wf-v1",
    )
    altered = rw.run_ridge_walk_forward_challenger(
        dataset=altered_test_dataset,
        fold=_fold(altered_test_dataset),
        specifications=specifications,
        fitting_code_revision="ridge-wf-v1",
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


def test_each_validation_trial_uses_exact_validation_partition_and_train_only_artifact() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    result = rw.run_ridge_walk_forward_challenger(
        dataset=dataset,
        fold=fold,
        specifications=(
            _spec("RIDGE-A", "-999"),
            _spec("RIDGE-B", "0"),
            _spec("RIDGE-C", "1"),
        ),
        fitting_code_revision="ridge-wf-v1",
    )

    for candidate in result.candidates:
        assert candidate.validation_trial.validation_example_ids == fold.validation_example_ids
        assert candidate.fitted.artifact.train_example_ids == fold.train_example_ids
        assert candidate.fitted.artifact.validation_used_for_fitting is False
        assert candidate.fitted.artifact.test_used_for_fitting is False


def test_signal_threshold_must_be_explicit_and_finite() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    missing = fp.ModelSpecification(
        candidate_id="RIDGE-MISSING-THRESHOLD",
        family=fp.ModelFamily.LINEAR_SCORE,
        feature_schema_version="RIDGE_WF_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=((lb.RIDGE_ALPHA_KEY, "0.1"),),
        random_seed=0,
    )

    with pytest.raises(mt.ModelTrainingError, match="RIDGE_SIGNAL_THRESHOLD_REQUIRED"):
        rw.run_ridge_walk_forward_challenger(
            dataset=dataset,
            fold=fold,
            specifications=(missing,),
            fitting_code_revision="ridge-wf-v1",
        )

    infinite = _spec("RIDGE-INF", "inf")
    with pytest.raises(mt.ModelTrainingError, match="RIDGE_SIGNAL_THRESHOLD_MUST_BE_FINITE"):
        rw.run_ridge_walk_forward_challenger(
            dataset=dataset,
            fold=fold,
            specifications=(infinite,),
            fitting_code_revision="ridge-wf-v1",
        )


def test_non_linear_family_cannot_enter_ridge_walk_forward() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    wrong_family = fp.ModelSpecification(
        candidate_id="TREE",
        family=fp.ModelFamily.TREE_ENSEMBLE,
        feature_schema_version="RIDGE_WF_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (lb.RIDGE_ALPHA_KEY, "0.1"),
            (rw.SIGNAL_THRESHOLD_KEY, "0"),
        ),
        random_seed=0,
    )

    with pytest.raises(mt.ModelTrainingError, match="REQUIRES_LINEAR_SCORE_FAMILY"):
        rw.run_ridge_walk_forward_challenger(
            dataset=dataset,
            fold=fold,
            specifications=(wrong_family,),
            fitting_code_revision="ridge-wf-v1",
        )
