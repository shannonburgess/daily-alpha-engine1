from __future__ import annotations

from dataclasses import replace

import pytest

from daily_alpha.model_control_benchmark import (
    SH24_CONTROL_IDENTITY,
    SH25_CHALLENGER_IDENTITY,
    ControlRole,
    FrozenControlEvaluation,
    MetricDelta,
    compare_against_frozen_controls,
)
from daily_alpha.model_fit_protocol import FinalTestEvaluation, SelectionMetric, ValidationSelection
from daily_alpha.model_training import ModelTrainingError, OutOfSampleMetrics

TEST_IDS = ("test-001", "test-002")
EVIDENCE_SHA = "e" * 64
ARTIFACT_SHA = "a" * 64


def _metrics(
    *,
    hit_rate: float = 0.5,
    expectancy_r: float = 0.2,
    profit_factor: float | None = 1.5,
    cumulative_r: float = 0.4,
    max_drawdown_r: float = 0.3,
) -> OutOfSampleMetrics:
    return OutOfSampleMetrics(
        sample_count=len(TEST_IDS),
        hit_rate=hit_rate,
        expectancy_r=expectancy_r,
        profit_factor=profit_factor,
        cumulative_r=cumulative_r,
        max_drawdown_r=max_drawdown_r,
    )


def _candidate() -> FinalTestEvaluation:
    selection = ValidationSelection(
        dataset_id="dataset-1",
        fold_id="fold-1",
        selection_metric=SelectionMetric.EXPECTANCY_R,
        selected_specification_id="spec-1",
        selected_artifact_sha256=ARTIFACT_SHA,
        trial_specification_ids=("spec-1", "spec-2"),
        selection_value=0.31,
    )
    return FinalTestEvaluation(
        dataset_id="dataset-1",
        fold_id="fold-1",
        selected_specification_id="spec-1",
        selected_artifact_sha256=ARTIFACT_SHA,
        test_example_ids=TEST_IDS,
        metrics=_metrics(
            hit_rate=0.75,
            expectancy_r=0.45,
            profit_factor=2.0,
            cumulative_r=0.9,
            max_drawdown_r=0.2,
        ),
        selection=selection,
    )


def _control(
    role: ControlRole,
    *,
    dataset_id: str = "dataset-1",
    fold_id: str = "fold-1",
    test_example_ids: tuple[str, ...] = TEST_IDS,
    evidence_sha: str = EVIDENCE_SHA,
) -> FrozenControlEvaluation:
    if role is ControlRole.SH24_CONTROL:
        identity = SH24_CONTROL_IDENTITY
        metrics = _metrics(
            hit_rate=0.5,
            expectancy_r=0.1,
            profit_factor=1.2,
            cumulative_r=0.2,
            max_drawdown_r=0.4,
        )
    else:
        identity = SH25_CHALLENGER_IDENTITY
        metrics = _metrics(
            hit_rate=0.6,
            expectancy_r=0.25,
            profit_factor=1.6,
            cumulative_r=0.5,
            max_drawdown_r=0.25,
        )
    return FrozenControlEvaluation(
        role=role,
        model_id=identity.model_id,
        strategy_version=identity.strategy_version,
        source_path=identity.source_path,
        source_blob_sha=identity.source_blob_sha,
        process_orders_on_close=identity.process_orders_on_close,
        dataset_id=dataset_id,
        fold_id=fold_id,
        test_example_ids=test_example_ids,
        test_evidence_sha256=evidence_sha,
        metrics=metrics,
    )


def test_benchmark_is_deterministic_and_compares_candidate_to_both_frozen_controls() -> None:
    candidate = _candidate()
    sh24 = _control(ControlRole.SH24_CONTROL)
    sh25 = _control(ControlRole.SH25_CHALLENGER)

    first = compare_against_frozen_controls(
        candidate=candidate,
        candidate_test_evidence_sha256=EVIDENCE_SHA,
        sh24_control=sh24,
        sh25_control=sh25,
    )
    second = compare_against_frozen_controls(
        candidate=candidate,
        candidate_test_evidence_sha256=EVIDENCE_SHA,
        sh24_control=sh24,
        sh25_control=sh25,
    )

    assert first == second
    assert first.benchmark_id == second.benchmark_id
    assert len(first.benchmark_id) == 64
    assert first.sh24_delta == MetricDelta(
        hit_rate=0.25,
        expectancy_r=0.35,
        profit_factor=0.8,
        cumulative_r=0.7,
        max_drawdown_r=-0.2,
    )
    assert first.sh25_delta.hit_rate == pytest.approx(0.15)
    assert first.sh25_delta.expectancy_r == pytest.approx(0.2)
    assert first.sh25_delta.profit_factor == pytest.approx(0.4)
    assert first.sh25_delta.cumulative_r == pytest.approx(0.4)
    assert first.sh25_delta.max_drawdown_r == pytest.approx(-0.05)
    assert first.test_influenced_selection is False
    assert first.retuning_authorized is False
    assert first.promotion_authorized is False
    assert first.paper_mutation_authorized is False
    assert first.trading_authorized is False
    assert first.live_trading_enabled is False
    assert first.research_only is True


@pytest.mark.parametrize(
    ("role", "identity"),
    [
        (ControlRole.SH24_CONTROL, SH24_CONTROL_IDENTITY),
        (ControlRole.SH25_CHALLENGER, SH25_CHALLENGER_IDENTITY),
    ],
)
def test_frozen_controls_require_exact_source_version_and_close_order_semantics(
    role: ControlRole,
    identity: object,
) -> None:
    control = _control(role)
    assert control.source_frozen is True
    assert control.process_orders_on_close is True

    with pytest.raises(ModelTrainingError, match=f"{role.value}_SOURCE_IDENTITY_MISMATCH"):
        FrozenControlEvaluation(
            role=role,
            model_id=control.model_id,
            strategy_version=f"{control.strategy_version}-mutated",
            source_path=control.source_path,
            source_blob_sha=control.source_blob_sha,
            process_orders_on_close=True,
            dataset_id=control.dataset_id,
            fold_id=control.fold_id,
            test_example_ids=control.test_example_ids,
            test_evidence_sha256=control.test_evidence_sha256,
            metrics=control.metrics,
        )

    with pytest.raises(ModelTrainingError, match=f"{role.value}_SOURCE_IDENTITY_MISMATCH"):
        replace(control, process_orders_on_close=False)

    assert identity == (
        SH24_CONTROL_IDENTITY if role is ControlRole.SH24_CONTROL else SH25_CHALLENGER_IDENTITY
    )


def test_benchmark_rejects_any_test_cohort_drift() -> None:
    candidate = _candidate()
    mismatched = _control(
        ControlRole.SH25_CHALLENGER,
        test_example_ids=("test-002", "test-001"),
    )

    with pytest.raises(ModelTrainingError, match="CONTROL_BENCHMARK_TEST_COHORT_MISMATCH"):
        compare_against_frozen_controls(
            candidate=candidate,
            candidate_test_evidence_sha256=EVIDENCE_SHA,
            sh24_control=_control(ControlRole.SH24_CONTROL),
            sh25_control=mismatched,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("dataset_id", "dataset-elsewhere", "CONTROL_BENCHMARK_DATASET_ID_MISMATCH"),
        ("fold_id", "fold-elsewhere", "CONTROL_BENCHMARK_FOLD_ID_MISMATCH"),
        ("evidence_sha", "f" * 64, "CONTROL_BENCHMARK_TEST_EVIDENCE_MISMATCH"),
    ],
)
def test_benchmark_rejects_lineage_drift(field: str, value: str, match: str) -> None:
    kwargs = {field: value}
    sh25 = _control(ControlRole.SH25_CHALLENGER, **kwargs)

    with pytest.raises(ModelTrainingError, match=match):
        compare_against_frozen_controls(
            candidate=_candidate(),
            candidate_test_evidence_sha256=EVIDENCE_SHA,
            sh24_control=_control(ControlRole.SH24_CONTROL),
            sh25_control=sh25,
        )


def test_control_metrics_must_cover_exact_test_cohort() -> None:
    identity = SH24_CONTROL_IDENTITY
    with pytest.raises(ModelTrainingError, match="CONTROL_TEST_METRIC_SAMPLE_COUNT_MISMATCH"):
        FrozenControlEvaluation(
            role=ControlRole.SH24_CONTROL,
            model_id=identity.model_id,
            strategy_version=identity.strategy_version,
            source_path=identity.source_path,
            source_blob_sha=identity.source_blob_sha,
            process_orders_on_close=True,
            dataset_id="dataset-1",
            fold_id="fold-1",
            test_example_ids=TEST_IDS,
            test_evidence_sha256=EVIDENCE_SHA,
            metrics=OutOfSampleMetrics(
                sample_count=1,
                hit_rate=1.0,
                expectancy_r=0.5,
                profit_factor=None,
                cumulative_r=0.5,
                max_drawdown_r=0.0,
            ),
        )


@pytest.mark.parametrize(
    "flag",
    [
        "promotion_authorized",
        "paper_mutation_authorized",
        "trading_authorized",
        "live_trading_enabled",
    ],
)
def test_control_evaluation_cannot_gain_execution_or_promotion_authority(flag: str) -> None:
    with pytest.raises(
        ModelTrainingError,
        match="CONTROL_EVALUATION_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING",
    ):
        replace(_control(ControlRole.SH24_CONTROL), **{flag: True})


@pytest.mark.parametrize(
    "flag",
    [
        "retuning_authorized",
        "promotion_authorized",
        "paper_mutation_authorized",
        "trading_authorized",
        "live_trading_enabled",
    ],
)
def test_benchmark_cannot_gain_retuning_promotion_or_execution_authority(flag: str) -> None:
    benchmark = compare_against_frozen_controls(
        candidate=_candidate(),
        candidate_test_evidence_sha256=EVIDENCE_SHA,
        sh24_control=_control(ControlRole.SH24_CONTROL),
        sh25_control=_control(ControlRole.SH25_CHALLENGER),
    )
    expected = (
        "TEST_BENCHMARK_CANNOT_INFLUENCE_SELECTION_OR_RETUNING"
        if flag == "retuning_authorized"
        else "CONTROL_BENCHMARK_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING"
    )
    with pytest.raises(ModelTrainingError, match=expected):
        replace(benchmark, **{flag: True})


def test_direct_benchmark_construction_rejects_fabricated_metric_deltas() -> None:
    candidate = _candidate()
    sh24 = _control(ControlRole.SH24_CONTROL)
    sh25 = _control(ControlRole.SH25_CHALLENGER)
    benchmark = compare_against_frozen_controls(
        candidate=candidate,
        candidate_test_evidence_sha256=EVIDENCE_SHA,
        sh24_control=sh24,
        sh25_control=sh25,
    )

    with pytest.raises(ModelTrainingError, match="SH24_BENCHMARK_DELTA_MISMATCH"):
        replace(
            benchmark,
            sh24_delta=MetricDelta(
                hit_rate=99.0,
                expectancy_r=99.0,
                profit_factor=99.0,
                cumulative_r=99.0,
                max_drawdown_r=99.0,
            ),
        )


def test_missing_profit_factor_remains_missing_instead_of_being_invented() -> None:
    candidate = _candidate()
    candidate = replace(
        candidate,
        metrics=replace(candidate.metrics, profit_factor=None),
    )
    benchmark = compare_against_frozen_controls(
        candidate=candidate,
        candidate_test_evidence_sha256=EVIDENCE_SHA,
        sh24_control=_control(ControlRole.SH24_CONTROL),
        sh25_control=_control(ControlRole.SH25_CHALLENGER),
    )

    assert benchmark.sh24_delta.profit_factor is None
    assert benchmark.sh25_delta.profit_factor is None
