import datetime as dt

import pytest

import daily_alpha.model_training as mt


BASE = dt.datetime(2026, 1, 2, 21, 0, tzinfo=dt.UTC)


def _example(symbol: str, day: int, realized_r: float = 1.0) -> mt.TrainingExample:
    decision_at = BASE + dt.timedelta(days=day)
    return mt.TrainingExample(
        security_id=symbol,
        decision_at=decision_at,
        feature_known_at=decision_at - dt.timedelta(minutes=1),
        label_known_at=decision_at + dt.timedelta(days=5),
        label_horizon_days=5,
        features=(("adx", 24.0 + day), ("residual_momentum", 0.1 + day / 100.0)),
        realized_r=realized_r,
        evidence_ids=(f"market-{symbol}-{day}", f"feature-{symbol}-{day}"),
    )


def _dataset(examples: tuple[mt.TrainingExample, ...]) -> mt.TrainingDatasetSnapshot:
    return mt.TrainingDatasetSnapshot(
        as_of=BASE + dt.timedelta(days=60),
        feature_schema_version="TRAINING_FEATURES_V1",
        label_definition="5D_REALIZED_R_AFTER_DECISION",
        examples=examples,
        source_revisions=("bars:v1", "features:v1", "labels:v1"),
    )


def test_feature_must_be_known_by_historical_decision_boundary() -> None:
    with pytest.raises(mt.ModelTrainingError, match="FEATURE_KNOWN_AFTER_DECISION"):
        mt.TrainingExample(
            security_id="MU",
            decision_at=BASE,
            feature_known_at=BASE + dt.timedelta(seconds=1),
            label_known_at=BASE + dt.timedelta(days=5),
            label_horizon_days=5,
            features=(("adx", 30.0),),
            realized_r=1.0,
            evidence_ids=("point-in-time-source",),
        )


def test_label_must_mature_after_decision() -> None:
    with pytest.raises(mt.ModelTrainingError, match="LABEL_MUST_MATURE_AFTER_DECISION"):
        mt.TrainingExample(
            security_id="MU",
            decision_at=BASE,
            feature_known_at=BASE,
            label_known_at=BASE,
            label_horizon_days=5,
            features=(("adx", 30.0),),
            realized_r=1.0,
            evidence_ids=("point-in-time-source",),
        )


def test_dataset_rejects_label_not_mature_by_snapshot_cutoff() -> None:
    example = _example("MU", 10)
    with pytest.raises(mt.ModelTrainingError, match="LABEL_NOT_MATURE_BY_DATASET_AS_OF"):
        mt.TrainingDatasetSnapshot(
            as_of=example.decision_at + dt.timedelta(days=1),
            feature_schema_version="TRAINING_FEATURES_V1",
            label_definition="5D_REALIZED_R_AFTER_DECISION",
            examples=(example,),
            source_revisions=("bars:v1",),
        )


def test_dataset_identity_is_input_order_independent() -> None:
    mu = _example("MU", 1)
    nvda = _example("NVDA", 2)

    first = _dataset((mu, nvda))
    second = _dataset((nvda, mu))

    assert first.dataset_id == second.dataset_id
    assert tuple(item.security_id for item in first.examples) == ("MU", "NVDA")


def test_dataset_rejects_duplicate_security_decision_example() -> None:
    first = _example("MU", 1)
    duplicate = mt.TrainingExample(
        security_id="MU",
        decision_at=first.decision_at,
        feature_known_at=first.feature_known_at,
        label_known_at=first.label_known_at,
        label_horizon_days=5,
        features=(("adx", 99.0),),
        realized_r=-1.0,
        evidence_ids=("different-evidence",),
    )

    with pytest.raises(mt.ModelTrainingError, match="DUPLICATE_SECURITY_DECISION_EXAMPLE"):
        _dataset((first, duplicate))


def test_walk_forward_fold_keeps_train_validation_test_disjoint() -> None:
    dataset = _dataset(
        (
            _example("A", 1),
            _example("B", 2),
            _example("C", 10),
            _example("D", 11),
            _example("E", 20),
            _example("F", 21),
        )
    )
    window = mt.WalkForwardWindow(
        fold_id="WF-1",
        train_start=BASE,
        train_end=BASE + dt.timedelta(days=5),
        validation_start=BASE + dt.timedelta(days=9),
        validation_end=BASE + dt.timedelta(days=15),
        test_start=BASE + dt.timedelta(days=19),
        test_end=BASE + dt.timedelta(days=25),
    )

    fold = mt.build_walk_forward_fold(dataset, window)

    assert len(fold.train_example_ids) == 2
    assert len(fold.validation_example_ids) == 2
    assert len(fold.test_example_ids) == 2
    assert not (set(fold.train_example_ids) & set(fold.test_example_ids))


def test_walk_forward_rejects_validation_or_test_use_for_fitting() -> None:
    example_ids = (_example("MU", 1).example_id,)
    window = mt.WalkForwardWindow(
        fold_id="WF-1",
        train_start=BASE,
        train_end=BASE + dt.timedelta(days=2),
        validation_start=BASE + dt.timedelta(days=3),
        validation_end=BASE + dt.timedelta(days=4),
        test_start=BASE + dt.timedelta(days=5),
        test_end=BASE + dt.timedelta(days=6),
    )

    with pytest.raises(mt.ModelTrainingError, match="OUT_OF_SAMPLE_DATA_CANNOT_BE_USED_FOR_FITTING"):
        mt.WalkForwardFold(
            window=window,
            train_example_ids=example_ids,
            validation_example_ids=("validation",),
            test_example_ids=("test",),
            fitting_may_use_validation=True,
        )


def test_oos_metrics_are_computed_only_from_supplied_realized_results() -> None:
    metrics = mt.evaluate_oos_realized_r((1.0, -0.5, 2.0, -1.0))

    assert metrics.sample_count == 4
    assert metrics.hit_rate == 0.5
    assert metrics.expectancy_r == pytest.approx(0.375)
    assert metrics.profit_factor == pytest.approx(2.0)
    assert metrics.cumulative_r == pytest.approx(1.5)
    assert metrics.max_drawdown_r == pytest.approx(1.0)


def test_research_candidate_cannot_self_promote_or_authorize_trading() -> None:
    metrics = mt.evaluate_oos_realized_r((1.0, -0.25, 0.5))

    with pytest.raises(
        mt.ModelTrainingError,
        match="RESEARCH_ASSESSMENT_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING",
    ):
        mt.ResearchModelCandidateAssessment(
            candidate_id="ML-CHALLENGER-1",
            dataset_id="dataset-1",
            fold_id="WF-1",
            validation_metrics=metrics,
            test_metrics=metrics,
            promotion_authorized=True,
        )
