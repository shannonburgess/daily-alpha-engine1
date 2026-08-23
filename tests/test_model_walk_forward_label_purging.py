import datetime as dt

import pytest

import daily_alpha.model_training as mt

BASE = dt.datetime(2026, 1, 2, 21, 0, tzinfo=dt.UTC)


def _example(
    symbol: str,
    decision_day: int,
    label_day: int,
    *,
    realized_r: float = 1.0,
) -> mt.TrainingExample:
    decision_at = BASE + dt.timedelta(days=decision_day)
    return mt.TrainingExample(
        security_id=symbol,
        decision_at=decision_at,
        feature_known_at=decision_at - dt.timedelta(minutes=1),
        label_known_at=BASE + dt.timedelta(days=label_day),
        label_horizon_days=max(1, label_day - decision_day),
        features=(("adx", 25.0 + decision_day),),
        realized_r=realized_r,
        evidence_ids=(f"evidence-{symbol}-{decision_day}",),
    )


def _dataset(*examples: mt.TrainingExample) -> mt.TrainingDatasetSnapshot:
    return mt.TrainingDatasetSnapshot(
        as_of=BASE + dt.timedelta(days=60),
        feature_schema_version="PIT_FEATURES_V1",
        label_definition="REALIZED_R",
        examples=tuple(examples),
        source_revisions=("features:pit-v1", "labels:pit-v1"),
    )


def _window() -> mt.WalkForwardWindow:
    return mt.WalkForwardWindow(
        fold_id="WF-PURGED-1",
        train_start=BASE,
        train_end=BASE + dt.timedelta(days=5),
        validation_start=BASE + dt.timedelta(days=9),
        validation_end=BASE + dt.timedelta(days=15),
        test_start=BASE + dt.timedelta(days=19),
        test_end=BASE + dt.timedelta(days=25),
    )


def test_train_label_maturing_at_validation_start_is_purged_from_fit_partition() -> None:
    safe_train = _example("A", 1, 6)
    leaking_train = _example("B", 4, 9)
    validation = _example("C", 10, 15)
    test = _example("D", 20, 25)

    fold = mt.build_walk_forward_fold(
        _dataset(safe_train, leaking_train, validation, test),
        _window(),
    )

    assert fold.train_example_ids == (safe_train.example_id,)
    assert fold.purged_train_example_ids == (leaking_train.example_id,)
    assert leaking_train.example_id not in fold.train_example_ids


def test_validation_label_maturing_at_test_start_is_purged_from_selection_partition() -> None:
    train = _example("A", 1, 6)
    safe_validation = _example("B", 10, 15)
    leaking_validation = _example("C", 14, 19)
    test = _example("D", 20, 25)

    fold = mt.build_walk_forward_fold(
        _dataset(train, safe_validation, leaking_validation, test),
        _window(),
    )

    assert fold.validation_example_ids == (safe_validation.example_id,)
    assert fold.purged_validation_example_ids == (leaking_validation.example_id,)
    assert leaking_validation.example_id not in fold.validation_example_ids


def test_labels_known_one_instant_before_next_stage_are_allowed() -> None:
    train = _example("A", 1, 8)
    validation = _example("B", 10, 18)
    test = _example("C", 20, 25)

    fold = mt.build_walk_forward_fold(_dataset(train, validation, test), _window())

    assert fold.train_example_ids == (train.example_id,)
    assert fold.validation_example_ids == (validation.example_id,)
    assert fold.purged_train_example_ids == ()
    assert fold.purged_validation_example_ids == ()


def test_purging_that_empties_train_partition_fails_closed() -> None:
    leaking_train = _example("A", 4, 9)
    validation = _example("B", 10, 15)
    test = _example("C", 20, 25)

    with pytest.raises(mt.ModelTrainingError, match="TRAIN_PARTITION_EMPTY"):
        mt.build_walk_forward_fold(
            _dataset(leaking_train, validation, test),
            _window(),
        )


def test_purged_examples_are_in_partition_lineage_and_cannot_overlap_active_ids() -> None:
    train = _example("A", 1, 6)
    leaking_train = _example("B", 4, 9)
    validation = _example("C", 10, 15)
    test = _example("D", 20, 25)
    fold = mt.build_walk_forward_fold(
        _dataset(train, leaking_train, validation, test),
        _window(),
    )

    assert len(fold.partition_id) == 64
    with pytest.raises(mt.ModelTrainingError, match="PURGED_EXAMPLE_CANNOT_REMAIN_IN_ACTIVE_PARTITION"):
        mt.WalkForwardFold(
            window=_window(),
            train_example_ids=(train.example_id,),
            validation_example_ids=(validation.example_id,),
            test_example_ids=(test.example_id,),
            purged_train_example_ids=(train.example_id,),
        )
