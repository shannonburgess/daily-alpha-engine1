import datetime as dt

import pytest

import daily_alpha.model_fit_protocol as fp
import daily_alpha.model_training as mt

BASE = dt.datetime(2026, 1, 2, 21, 0, tzinfo=dt.UTC)


def _fold() -> mt.WalkForwardFold:
    window = mt.WalkForwardWindow(
        fold_id="WF-1",
        train_start=BASE,
        train_end=BASE + dt.timedelta(days=9),
        validation_start=BASE + dt.timedelta(days=10),
        validation_end=BASE + dt.timedelta(days=19),
        test_start=BASE + dt.timedelta(days=20),
        test_end=BASE + dt.timedelta(days=29),
    )
    return mt.WalkForwardFold(
        window=window,
        train_example_ids=("train-1", "train-2"),
        validation_example_ids=("val-1", "val-2"),
        test_example_ids=("test-1", "test-2"),
    )


def _spec(candidate_id: str, alpha: str) -> fp.ModelSpecification:
    return fp.ModelSpecification(
        candidate_id=candidate_id,
        family=fp.ModelFamily.GRADIENT_BOOSTED_TREES,
        feature_schema_version="TRAINING_FEATURES_V1",
        feature_names=("residual_momentum", "adx"),
        hyperparameters=(("alpha", alpha), ("depth", "3")),
        random_seed=42,
    )


def _artifact(spec: fp.ModelSpecification, sha_char: str) -> fp.FittedModelArtifact:
    return fp.FittedModelArtifact(
        dataset_id="dataset-1",
        fold_id="WF-1",
        specification_id=spec.specification_id,
        train_example_ids=("train-1", "train-2"),
        artifact_sha256=sha_char * 64,
        fitting_code_revision="fit-code-v1",
    )


def _metrics(expectancy: float, drawdown: float = 1.0) -> mt.OutOfSampleMetrics:
    return mt.OutOfSampleMetrics(
        sample_count=2,
        hit_rate=0.5,
        expectancy_r=expectancy,
        profit_factor=1.5,
        cumulative_r=expectancy * 2,
        max_drawdown_r=drawdown,
    )


def test_model_specification_identity_is_order_independent() -> None:
    first = _spec("ML-1", "0.1")
    second = fp.ModelSpecification(
        candidate_id="ML-1",
        family=fp.ModelFamily.GRADIENT_BOOSTED_TREES,
        feature_schema_version="TRAINING_FEATURES_V1",
        feature_names=("adx", "residual_momentum"),
        hyperparameters=(("depth", "3"), ("alpha", "0.1")),
        random_seed=42,
    )

    assert first.specification_id == second.specification_id


def test_fitted_artifact_must_use_exact_train_partition() -> None:
    artifact = _artifact(_spec("ML-1", "0.1"), "a")
    artifact.assert_matches_fold(_fold())

    bad = fp.FittedModelArtifact(
        dataset_id="dataset-1",
        fold_id="WF-1",
        specification_id=artifact.specification_id,
        train_example_ids=("train-1",),
        artifact_sha256="b" * 64,
        fitting_code_revision="fit-code-v1",
    )
    with pytest.raises(mt.ModelTrainingError, match="FIT_MUST_USE_EXACT_TRAIN_PARTITION"):
        bad.assert_matches_fold(_fold())


def test_fitted_artifact_rejects_out_of_sample_data_for_fitting() -> None:
    with pytest.raises(mt.ModelTrainingError, match="OUT_OF_SAMPLE_DATA_USED_FOR_FITTING"):
        fp.FittedModelArtifact(
            dataset_id="dataset-1",
            fold_id="WF-1",
            specification_id=_spec("ML-1", "0.1").specification_id,
            train_example_ids=("train-1", "train-2"),
            artifact_sha256="a" * 64,
            fitting_code_revision="fit-code-v1",
            validation_used_for_fitting=True,
        )


def test_validation_selects_best_candidate_without_test_metrics() -> None:
    fold = _fold()
    weak = _artifact(_spec("ML-WEAK", "0.1"), "a")
    strong = _artifact(_spec("ML-STRONG", "0.2"), "b")
    trials = (
        fp.ValidationTrial(weak, fold.validation_example_ids, _metrics(0.10)),
        fp.ValidationTrial(strong, fold.validation_example_ids, _metrics(0.35)),
    )

    selection = fp.select_validation_trial(
        dataset_id="dataset-1",
        fold=fold,
        trials=trials,
        metric=fp.SelectionMetric.EXPECTANCY_R,
    )

    assert selection.selected_specification_id == strong.specification_id
    assert selection.selected_artifact_sha256 == "b" * 64
    assert selection.selection_value == pytest.approx(0.35)
    assert selection.test_metrics_observed is False


def test_validation_selection_rejects_test_observation() -> None:
    with pytest.raises(
        mt.ModelTrainingError,
        match="TEST_DATA_CANNOT_INFLUENCE_VALIDATION_SELECTION",
    ):
        fp.ValidationSelection(
            dataset_id="dataset-1",
            fold_id="WF-1",
            selection_metric=fp.SelectionMetric.EXPECTANCY_R,
            selected_specification_id="spec-1",
            selected_artifact_sha256="a" * 64,
            trial_specification_ids=("spec-1",),
            selection_value=0.2,
            test_metrics_observed=True,
        )


def test_final_test_uses_exact_untouched_test_partition() -> None:
    fold = _fold()
    artifact = _artifact(_spec("ML-1", "0.1"), "a")
    selection = fp.select_validation_trial(
        dataset_id="dataset-1",
        fold=fold,
        trials=(fp.ValidationTrial(artifact, fold.validation_example_ids, _metrics(0.2)),),
    )

    evaluation = fp.build_final_test_evaluation(
        dataset_id="dataset-1",
        fold=fold,
        selection=selection,
        test_example_ids=fold.test_example_ids,
        metrics=_metrics(0.15),
    )

    assert evaluation.metrics.expectancy_r == pytest.approx(0.15)
    assert evaluation.retuned_after_test is False
    assert evaluation.promotion_authorized is False
    assert evaluation.trading_authorized is False
    assert evaluation.live_trading_enabled is False


def test_final_test_rejects_partial_test_partition() -> None:
    fold = _fold()
    artifact = _artifact(_spec("ML-1", "0.1"), "a")
    selection = fp.select_validation_trial(
        dataset_id="dataset-1",
        fold=fold,
        trials=(fp.ValidationTrial(artifact, fold.validation_example_ids, _metrics(0.2)),),
    )
    one_sample = mt.OutOfSampleMetrics(
        sample_count=1,
        hit_rate=1.0,
        expectancy_r=0.2,
        profit_factor=None,
        cumulative_r=0.2,
        max_drawdown_r=0.0,
    )

    with pytest.raises(mt.ModelTrainingError, match="FINAL_TEST_MUST_USE_EXACT_TEST_PARTITION"):
        fp.build_final_test_evaluation(
            dataset_id="dataset-1",
            fold=fold,
            selection=selection,
            test_example_ids=("test-1",),
            metrics=one_sample,
        )


def test_final_test_cannot_be_retuned_or_self_promoted() -> None:
    fold = _fold()
    artifact = _artifact(_spec("ML-1", "0.1"), "a")
    selection = fp.select_validation_trial(
        dataset_id="dataset-1",
        fold=fold,
        trials=(fp.ValidationTrial(artifact, fold.validation_example_ids, _metrics(0.2)),),
    )

    with pytest.raises(mt.ModelTrainingError, match="MODEL_CANNOT_BE_RETUNED_AFTER_FINAL_TEST"):
        fp.FinalTestEvaluation(
            dataset_id="dataset-1",
            fold_id="WF-1",
            selected_specification_id=selection.selected_specification_id,
            selected_artifact_sha256=selection.selected_artifact_sha256,
            test_example_ids=fold.test_example_ids,
            metrics=_metrics(0.2),
            selection=selection,
            retuned_after_test=True,
        )
