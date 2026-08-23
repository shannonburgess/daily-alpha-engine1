import datetime as dt

import pytest

import daily_alpha.model_fit_protocol as fp
import daily_alpha.model_linear_baseline as lb
import daily_alpha.model_training as mt

BASE = dt.datetime(2025, 1, 2, 21, 0, tzinfo=dt.UTC)


def _example(symbol: str, day: int, x: float, z: float, realized_r: float) -> mt.TrainingExample:
    decision_at = BASE + dt.timedelta(days=day)
    return mt.TrainingExample(
        security_id=symbol,
        decision_at=decision_at,
        feature_known_at=decision_at,
        label_known_at=decision_at + dt.timedelta(days=5),
        label_horizon_days=5,
        features=(("x", x), ("z", z)),
        realized_r=realized_r,
        evidence_ids=(f"bars-{symbol}-{day}", f"features-{symbol}-{day}"),
    )


def _dataset(*, oos_shift: float = 0.0) -> mt.TrainingDatasetSnapshot:
    examples = (
        _example("A", 1, 0.0, 1.0, 0.5),
        _example("B", 2, 1.0, 0.0, 2.0),
        _example("C", 3, 2.0, 1.0, 4.5),
        _example("D", 4, 3.0, 2.0, 7.0),
        _example("E", 10, 4.0, 1.0, 8.5 + oos_shift),
        _example("F", 11, 5.0, 0.0, 10.0 + oos_shift),
        _example("G", 20, 6.0, 2.0, 13.0 - oos_shift),
        _example("H", 21, 7.0, 1.0, 14.5 - oos_shift),
    )
    return mt.TrainingDatasetSnapshot(
        as_of=BASE + dt.timedelta(days=40),
        feature_schema_version="LINEAR_FEATURES_V1",
        label_definition="5D_REALIZED_R",
        examples=examples,
        source_revisions=("fixture-bars-v1", "fixture-features-v1", "fixture-labels-v1"),
    )


def _fold(dataset: mt.TrainingDatasetSnapshot) -> mt.WalkForwardFold:
    return mt.build_walk_forward_fold(
        dataset,
        mt.WalkForwardWindow(
            fold_id="WF-LINEAR-1",
            train_start=BASE,
            train_end=BASE + dt.timedelta(days=5),
            validation_start=BASE + dt.timedelta(days=10),
            validation_end=BASE + dt.timedelta(days=12),
            test_start=BASE + dt.timedelta(days=20),
            test_end=BASE + dt.timedelta(days=22),
        ),
    )


def _spec(alpha: str = "0.1") -> fp.ModelSpecification:
    return fp.ModelSpecification(
        candidate_id="LINEAR-RIDGE-V1",
        family=fp.ModelFamily.LINEAR_SCORE,
        feature_schema_version="LINEAR_FEATURES_V1",
        feature_names=("x", "z"),
        hyperparameters=((lb.RIDGE_ALPHA_KEY, alpha),),
        random_seed=0,
    )


def test_linear_baseline_fits_exact_train_partition_with_artifact_lineage() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    fitted = lb.fit_linear_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )

    assert fitted.artifact.train_example_ids == fold.train_example_ids
    assert fitted.artifact.dataset_id == dataset.dataset_id
    assert fitted.artifact.fold_id == fold.window.fold_id
    assert fitted.artifact.artifact_sha256 == fitted.model.artifact_sha256
    assert len(fitted.model.coefficients) == 2
    assert fitted.artifact.promotion_authorized is False
    assert fitted.artifact.trading_authorized is False
    assert fitted.artifact.live_trading_enabled is False


def test_validation_and_test_labels_do_not_change_fitted_parameters() -> None:
    baseline = _dataset(oos_shift=0.0)
    altered_oos = _dataset(oos_shift=1000.0)

    first = lb.fit_linear_baseline(
        dataset=baseline,
        fold=_fold(baseline),
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )
    second = lb.fit_linear_baseline(
        dataset=altered_oos,
        fold=_fold(altered_oos),
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )

    assert first.model.feature_means == second.model.feature_means
    assert first.model.feature_scales == second.model.feature_scales
    assert first.model.coefficients == second.model.coefficients
    assert first.model.intercept == second.model.intercept
    assert first.model.dataset_id != second.model.dataset_id


def test_fit_is_deterministic_for_same_dataset_fold_and_specification() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    first = lb.fit_linear_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )
    second = lb.fit_linear_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )

    assert first.model == second.model
    assert first.model.artifact_sha256 == second.model.artifact_sha256
    assert first.artifact == second.artifact


def test_evaluation_uses_exact_validation_and_test_partitions() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    fitted = lb.fit_linear_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )

    validation = lb.evaluate_linear_baseline(
        dataset=dataset,
        fold=fold,
        fitted=fitted,
        partition=mt.DatasetPartition.VALIDATION,
    )
    test = lb.evaluate_linear_baseline(
        dataset=dataset,
        fold=fold,
        fitted=fitted,
        partition=mt.DatasetPartition.TEST,
    )

    assert validation.example_ids == fold.validation_example_ids
    assert test.example_ids == fold.test_example_ids
    assert validation.metrics.sample_count == len(fold.validation_example_ids)
    assert test.metrics.sample_count == len(fold.test_example_ids)
    assert validation.promotion_authorized is False
    assert validation.paper_mutation_authorized is False
    assert validation.trading_authorized is False
    assert validation.live_trading_enabled is False


def test_linear_baseline_requires_positive_explicit_ridge_alpha() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    missing_alpha = fp.ModelSpecification(
        candidate_id="LINEAR-NO-ALPHA",
        family=fp.ModelFamily.LINEAR_SCORE,
        feature_schema_version="LINEAR_FEATURES_V1",
        feature_names=("x", "z"),
        hyperparameters=(),
        random_seed=0,
    )
    with pytest.raises(mt.ModelTrainingError, match="RIDGE_ALPHA_REQUIRED"):
        lb.fit_linear_baseline(
            dataset=dataset,
            fold=fold,
            specification=missing_alpha,
            fitting_code_revision="linear-fit-v1",
        )

    with pytest.raises(mt.ModelTrainingError, match="RIDGE_ALPHA_MUST_BE_POSITIVE"):
        lb.fit_linear_baseline(
            dataset=dataset,
            fold=fold,
            specification=_spec("0"),
            fitting_code_revision="linear-fit-v1",
        )


def test_linear_baseline_rejects_non_linear_family_and_schema_mismatch() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    tree_spec = fp.ModelSpecification(
        candidate_id="TREE",
        family=fp.ModelFamily.TREE_ENSEMBLE,
        feature_schema_version="LINEAR_FEATURES_V1",
        feature_names=("x", "z"),
        hyperparameters=((lb.RIDGE_ALPHA_KEY, "0.1"),),
        random_seed=0,
    )

    with pytest.raises(mt.ModelTrainingError, match="REQUIRES_LINEAR_SCORE_FAMILY"):
        lb.fit_linear_baseline(
            dataset=dataset,
            fold=fold,
            specification=tree_spec,
            fitting_code_revision="linear-fit-v1",
        )

    bad_schema = fp.ModelSpecification(
        candidate_id="LINEAR-WRONG-SCHEMA",
        family=fp.ModelFamily.LINEAR_SCORE,
        feature_schema_version="OTHER_SCHEMA",
        feature_names=("x", "z"),
        hyperparameters=((lb.RIDGE_ALPHA_KEY, "0.1"),),
        random_seed=0,
    )
    with pytest.raises(mt.ModelTrainingError, match="FEATURE_SCHEMA_MISMATCH"):
        lb.fit_linear_baseline(
            dataset=dataset,
            fold=fold,
            specification=bad_schema,
            fitting_code_revision="linear-fit-v1",
        )


def test_model_prediction_fails_closed_when_required_feature_is_missing() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    fitted = lb.fit_linear_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="linear-fit-v1",
    )
    incomplete = mt.TrainingExample(
        security_id="MISSING",
        decision_at=BASE,
        feature_known_at=BASE,
        label_known_at=BASE + dt.timedelta(days=5),
        label_horizon_days=5,
        features=(("x", 1.0),),
        realized_r=1.0,
        evidence_ids=("fixture",),
    )

    with pytest.raises(mt.ModelTrainingError, match="MISSING_FEATURES:z"):
        fitted.model.predict(incomplete)
