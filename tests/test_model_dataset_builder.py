import datetime as dt

import pytest

import daily_alpha.model_dataset_builder as builder

BASE = dt.datetime(2026, 1, 2, 21, 0, tzinfo=dt.UTC)


def _policy() -> builder.TrainingDatasetAssemblyPolicy:
    return builder.TrainingDatasetAssemblyPolicy(
        feature_schema_version="DAILY_ALPHA_TRAINING_FEATURES_V1",
        label_definition="5D_REALIZED_R_AFTER_DECISION",
        required_feature_names=("adx", "residual_momentum"),
        label_horizon_days=5,
    )


def _feature(
    symbol: str,
    day: int,
    name: str,
    value: float,
    *,
    known_offset_minutes: int = -1,
    evidence_suffix: str = "v1",
) -> builder.PointInTimeFeatureObservation:
    decision_at = BASE + dt.timedelta(days=day)
    return builder.PointInTimeFeatureObservation(
        security_id=symbol,
        decision_at=decision_at,
        feature_name=name,
        feature_value=value,
        known_at=decision_at + dt.timedelta(minutes=known_offset_minutes),
        evidence_id=f"feature:{symbol}:{day}:{name}:{evidence_suffix}",
        source_revision=f"features:{evidence_suffix}",
    )


def _label(
    symbol: str,
    day: int,
    realized_r: float,
    *,
    known_after_days: int = 5,
    evidence_suffix: str = "v1",
) -> builder.RealizedRLabelObservation:
    decision_at = BASE + dt.timedelta(days=day)
    return builder.RealizedRLabelObservation(
        security_id=symbol,
        decision_at=decision_at,
        horizon_days=5,
        realized_r=realized_r,
        known_at=decision_at + dt.timedelta(days=known_after_days),
        evidence_ids=(f"label:{symbol}:{day}:{evidence_suffix}",),
        source_revision=f"labels:{evidence_suffix}",
    )


def test_builds_point_in_time_dataset_with_exact_lineage() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0),
        _feature("MU", 1, "residual_momentum", 0.14),
    )
    label = _label("MU", 1, 1.25)

    result = builder.build_point_in_time_training_dataset(
        as_of=BASE + dt.timedelta(days=20),
        policy=_policy(),
        feature_observations=features,
        label_observations=(label,),
    )

    assert len(result.dataset.examples) == 1
    example = result.dataset.examples[0]
    assert example.security_id == "MU"
    assert example.features == (("adx", 27.0), ("residual_momentum", 0.14))
    assert example.realized_r == 1.25
    assert set(example.evidence_ids) == {
        "feature:MU:1:adx:v1",
        "feature:MU:1:residual_momentum:v1",
        "label:MU:1:v1",
    }
    assert result.policy_id == _policy().policy_id
    assert result.dataset.source_revisions == (
        f"assembly-policy:{result.policy_id}",
        "features:v1",
        "labels:v1",
    )
    assert result.paper_mutation_authorized is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_dataset_assembly_identity_is_input_order_and_duplicate_stable() -> None:
    adx = _feature("MU", 1, "adx", 27.0)
    residual = _feature("MU", 1, "residual_momentum", 0.14)
    label = _label("MU", 1, 1.25)
    as_of = BASE + dt.timedelta(days=20)

    first = builder.build_point_in_time_training_dataset(
        as_of=as_of,
        policy=_policy(),
        feature_observations=(adx, residual),
        label_observations=(label,),
    )
    second = builder.build_point_in_time_training_dataset(
        as_of=as_of,
        policy=_policy(),
        feature_observations=(residual, adx, adx),
        label_observations=(label, label),
    )

    assert first.dataset.dataset_id == second.dataset.dataset_id
    assert first.assembly_id == second.assembly_id


def test_immature_labels_are_explicitly_excluded_without_leaking() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0),
        _feature("MU", 1, "residual_momentum", 0.14),
        _feature("NVDA", 10, "adx", 31.0),
        _feature("NVDA", 10, "residual_momentum", 0.22),
    )
    mature = _label("MU", 1, 1.25)
    immature = _label("NVDA", 10, -0.5, known_after_days=15)

    result = builder.build_point_in_time_training_dataset(
        as_of=BASE + dt.timedelta(days=20),
        policy=_policy(),
        feature_observations=features,
        label_observations=(mature, immature),
    )

    assert tuple(item.security_id for item in result.dataset.examples) == ("MU",)
    assert result.excluded_immature_label_ids == (immature.label_id,)
    assert immature.label_id not in result.included_label_ids


def test_feature_observation_rejects_future_knowledge() -> None:
    decision_at = BASE
    with pytest.raises(builder.ModelTrainingError, match="FEATURE_KNOWN_AFTER_DECISION"):
        builder.PointInTimeFeatureObservation(
            security_id="MU",
            decision_at=decision_at,
            feature_name="adx",
            feature_value=27.0,
            known_at=decision_at + dt.timedelta(seconds=1),
            evidence_id="feature:future",
            source_revision="features:v1",
        )


def test_builder_rejects_feature_schema_drift() -> None:
    with pytest.raises(builder.ModelTrainingError, match="FEATURE_SCHEMA_MISMATCH"):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=(_feature("MU", 1, "adx", 27.0),),
            label_observations=(_label("MU", 1, 1.25),),
        )


def test_builder_rejects_conflicting_feature_observations() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0, evidence_suffix="first"),
        _feature("MU", 1, "adx", 99.0, evidence_suffix="second"),
        _feature("MU", 1, "residual_momentum", 0.14),
    )

    with pytest.raises(builder.ModelTrainingError, match="CONFLICTING_FEATURE_OBSERVATION"):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=(_label("MU", 1, 1.25),),
        )


def test_builder_rejects_conflicting_label_observations() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0),
        _feature("MU", 1, "residual_momentum", 0.14),
    )
    labels = (
        _label("MU", 1, 1.25, evidence_suffix="first"),
        _label("MU", 1, -1.0, evidence_suffix="second"),
    )

    with pytest.raises(builder.ModelTrainingError, match="CONFLICTING_LABEL_OBSERVATION"):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=labels,
        )


def test_builder_rejects_label_without_feature_row() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0),
        _feature("MU", 1, "residual_momentum", 0.14),
    )

    with pytest.raises(builder.ModelTrainingError, match="LABEL_WITHOUT_FEATURE_ROW"):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=(_label("NVDA", 2, 0.5),),
        )


def test_builder_rejects_feature_row_missing_label() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0),
        _feature("MU", 1, "residual_momentum", 0.14),
        _feature("NVDA", 2, "adx", 31.0),
        _feature("NVDA", 2, "residual_momentum", 0.22),
    )

    with pytest.raises(builder.ModelTrainingError, match="FEATURE_ROW_MISSING_LABEL"):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=(_label("MU", 1, 1.25),),
        )


def test_builder_rejects_wrong_label_horizon() -> None:
    features = (
        _feature("MU", 1, "adx", 27.0),
        _feature("MU", 1, "residual_momentum", 0.14),
    )
    wrong = builder.RealizedRLabelObservation(
        security_id="MU",
        decision_at=BASE + dt.timedelta(days=1),
        horizon_days=10,
        realized_r=1.25,
        known_at=BASE + dt.timedelta(days=11),
        evidence_ids=("label:wrong-horizon",),
        source_revision="labels:v1",
    )

    with pytest.raises(builder.ModelTrainingError, match="LABEL_HORIZON_MISMATCH"):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=(wrong,),
        )


def test_builder_rejects_future_decision_rows_at_snapshot_boundary() -> None:
    features = (
        _feature("MU", 30, "adx", 27.0),
        _feature("MU", 30, "residual_momentum", 0.14),
    )

    with pytest.raises(
        builder.ModelTrainingError,
        match="FUTURE_FEATURE_DECISION_AT_DATASET_AS_OF",
    ):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=(_label("MU", 30, 1.25),),
        )


def test_builder_rejects_all_immature_dataset() -> None:
    features = (
        _feature("MU", 10, "adx", 27.0),
        _feature("MU", 10, "residual_momentum", 0.14),
    )
    label = _label("MU", 10, 1.25, known_after_days=15)

    with pytest.raises(
        builder.ModelTrainingError,
        match="NO_MATURE_TRAINING_EXAMPLES_AT_DATASET_AS_OF",
    ):
        builder.build_point_in_time_training_dataset(
            as_of=BASE + dt.timedelta(days=20),
            policy=_policy(),
            feature_observations=features,
            label_observations=(label,),
        )
