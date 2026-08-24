import datetime as dt

import pytest

import daily_alpha.model_fit_protocol as fp
import daily_alpha.model_logistic_baseline as logistic
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


def _dataset(*, all_positive_train: bool = False) -> mt.TrainingDatasetSnapshot:
    train_r = (1.0, 2.0, 1.0, 2.0) if all_positive_train else (-2.0, -1.0, 1.0, 2.0)
    return mt.TrainingDatasetSnapshot(
        as_of=BASE + dt.timedelta(days=40),
        feature_schema_version="LOGISTIC_FEATURES_V1",
        label_definition="3D_REALIZED_R",
        examples=(
            _example("T0", 1, -2.0, train_r[0]),
            _example("T1", 2, -1.0, train_r[1]),
            _example("T2", 3, 1.0, train_r[2]),
            _example("T3", 4, 2.0, train_r[3]),
            _example("V0", 10, -3.0, -2.0),
            _example("V1", 11, 3.0, 2.0),
            _example("X0", 20, -4.0, -3.0),
            _example("X1", 21, 4.0, 3.0),
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


def _spec() -> fp.ModelSpecification:
    return fp.ModelSpecification(
        candidate_id="LOGISTIC-L2",
        family=fp.ModelFamily.LOGISTIC_CLASSIFIER,
        feature_schema_version="LOGISTIC_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (logistic.LOGISTIC_L2_KEY, "1.0"),
            (logistic.LOGISTIC_ITERATIONS_KEY, "12"),
        ),
        random_seed=0,
    )


def test_logistic_baseline_fits_exact_train_partition_and_separates_fixture() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    fitted = logistic.fit_logistic_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="logistic-v1",
    )

    by_symbol = {example.security_id: example for example in dataset.examples}
    assert fitted.artifact.train_example_ids == fold.train_example_ids
    assert fitted.artifact.validation_used_for_fitting is False
    assert fitted.artifact.test_used_for_fitting is False
    assert fitted.model.predict_probability(by_symbol["V1"]) > 0.5
    assert fitted.model.predict_probability(by_symbol["V0"]) < 0.5
    assert fitted.model.positive_class_rule == logistic.POSITIVE_CLASS_RULE


def test_logistic_baseline_is_deterministic_for_same_train_evidence() -> None:
    dataset = _dataset()
    fold = _fold(dataset)

    first = logistic.fit_logistic_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="logistic-v1",
    )
    second = logistic.fit_logistic_baseline(
        dataset=dataset,
        fold=fold,
        specification=_spec(),
        fitting_code_revision="logistic-v1",
    )

    assert first.model.artifact_bytes == second.model.artifact_bytes
    assert first.model.artifact_sha256 == second.model.artifact_sha256


def test_logistic_baseline_requires_both_train_classes() -> None:
    dataset = _dataset(all_positive_train=True)
    fold = _fold(dataset)

    with pytest.raises(
        mt.ModelTrainingError,
        match="LOGISTIC_BASELINE_TRAIN_REQUIRES_BOTH_CLASSES",
    ):
        logistic.fit_logistic_baseline(
            dataset=dataset,
            fold=fold,
            specification=_spec(),
            fitting_code_revision="logistic-v1",
        )


def test_logistic_baseline_requires_explicit_valid_solver_parameters() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    missing_l2 = fp.ModelSpecification(
        candidate_id="LOGISTIC-MISSING-L2",
        family=fp.ModelFamily.LOGISTIC_CLASSIFIER,
        feature_schema_version="LOGISTIC_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=((logistic.LOGISTIC_ITERATIONS_KEY, "12"),),
        random_seed=0,
    )

    with pytest.raises(mt.ModelTrainingError, match="LOGISTIC_BASELINE_L2_REQUIRED"):
        logistic.fit_logistic_baseline(
            dataset=dataset,
            fold=fold,
            specification=missing_l2,
            fitting_code_revision="logistic-v1",
        )

    bad_iterations = fp.ModelSpecification(
        candidate_id="LOGISTIC-BAD-ITERATIONS",
        family=fp.ModelFamily.LOGISTIC_CLASSIFIER,
        feature_schema_version="LOGISTIC_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (logistic.LOGISTIC_L2_KEY, "1.0"),
            (logistic.LOGISTIC_ITERATIONS_KEY, "0"),
        ),
        random_seed=0,
    )
    with pytest.raises(
        mt.ModelTrainingError,
        match="LOGISTIC_BASELINE_ITERATIONS_OUT_OF_RANGE",
    ):
        logistic.fit_logistic_baseline(
            dataset=dataset,
            fold=fold,
            specification=bad_iterations,
            fitting_code_revision="logistic-v1",
        )


def test_logistic_baseline_rejects_wrong_model_family() -> None:
    dataset = _dataset()
    fold = _fold(dataset)
    wrong_family = fp.ModelSpecification(
        candidate_id="NOT-LOGISTIC",
        family=fp.ModelFamily.LINEAR_SCORE,
        feature_schema_version="LOGISTIC_FEATURES_V1",
        feature_names=("x",),
        hyperparameters=(
            (logistic.LOGISTIC_L2_KEY, "1.0"),
            (logistic.LOGISTIC_ITERATIONS_KEY, "12"),
        ),
        random_seed=0,
    )

    with pytest.raises(
        mt.ModelTrainingError,
        match="LOGISTIC_BASELINE_REQUIRES_LOGISTIC_CLASSIFIER_FAMILY",
    ):
        logistic.fit_logistic_baseline(
            dataset=dataset,
            fold=fold,
            specification=wrong_family,
            fitting_code_revision="logistic-v1",
        )
