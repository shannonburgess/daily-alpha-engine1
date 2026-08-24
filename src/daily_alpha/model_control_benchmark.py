"""Leak-proof OOS benchmarking against the frozen SH24/SH25 research controls.

This module sits *after* validation selection and final untouched TEST evaluation.
It cannot fit, select, retune, promote, mutate PAPER, or authorize trading. Its only
job is to bind a research candidate and both frozen Pine controls to the exact same
TEST cohort and evidence artifact before reporting deterministic metric deltas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .model_fit_protocol import FinalTestEvaluation
from .model_training import ModelTrainingError, OutOfSampleMetrics
from .pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_SOURCE_PATH,
    PINE_V24_STRATEGY_VERSION,
)
from .pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_BLOB_SHA,
    PINE_V25_SOURCE_PATH,
    PINE_V25_STRATEGY_VERSION,
)


class ControlRole(StrEnum):
    SH24_CONTROL = "SH24_CONTROL"
    SH25_CHALLENGER = "SH25_CHALLENGER"


@dataclass(frozen=True, slots=True)
class FrozenControlIdentity:
    role: ControlRole
    model_id: str
    strategy_version: str
    source_path: str
    source_blob_sha: str
    process_orders_on_close: bool = True


SH24_CONTROL_IDENTITY = FrozenControlIdentity(
    role=ControlRole.SH24_CONTROL,
    model_id=PINE_V24_MODEL_ID,
    strategy_version=PINE_V24_STRATEGY_VERSION,
    source_path=PINE_V24_SOURCE_PATH,
    source_blob_sha=PINE_V24_SOURCE_BLOB_SHA,
)
SH25_CHALLENGER_IDENTITY = FrozenControlIdentity(
    role=ControlRole.SH25_CHALLENGER,
    model_id=PINE_V25_MODEL_ID,
    strategy_version=PINE_V25_STRATEGY_VERSION,
    source_path=PINE_V25_SOURCE_PATH,
    source_blob_sha=PINE_V25_SOURCE_BLOB_SHA,
)

_EXPECTED_IDENTITIES = {
    ControlRole.SH24_CONTROL: SH24_CONTROL_IDENTITY,
    ControlRole.SH25_CHALLENGER: SH25_CHALLENGER_IDENTITY,
}


@dataclass(frozen=True, slots=True)
class FrozenControlEvaluation:
    """One frozen control evaluated on the candidate's exact untouched TEST cohort."""

    role: ControlRole
    model_id: str
    strategy_version: str
    source_path: str
    source_blob_sha: str
    process_orders_on_close: bool
    dataset_id: str
    fold_id: str
    test_example_ids: tuple[str, ...]
    test_evidence_sha256: str
    metrics: OutOfSampleMetrics
    source_frozen: bool = True
    research_only: bool = True
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        try:
            role = ControlRole(self.role)
        except ValueError as exc:
            raise ModelTrainingError("UNKNOWN_FROZEN_CONTROL_ROLE") from exc
        object.__setattr__(self, "role", role)

        expected = _EXPECTED_IDENTITIES[role]
        observed_identity = (
            self.model_id,
            self.strategy_version,
            self.source_path,
            self.source_blob_sha,
            self.process_orders_on_close,
        )
        expected_identity = (
            expected.model_id,
            expected.strategy_version,
            expected.source_path,
            expected.source_blob_sha,
            expected.process_orders_on_close,
        )
        if observed_identity != expected_identity:
            raise ModelTrainingError(f"{role.value}_SOURCE_IDENTITY_MISMATCH")
        if not self.source_frozen:
            raise ModelTrainingError("CONTROL_SOURCE_MUST_REMAIN_FROZEN")
        if not self.dataset_id.strip() or not self.fold_id.strip():
            raise ModelTrainingError("CONTROL_DATASET_AND_FOLD_REQUIRED")
        _require_example_ids(self.test_example_ids, "CONTROL_TEST")
        _require_sha256(self.test_evidence_sha256, "CONTROL_TEST_EVIDENCE_SHA256")
        if self.metrics.sample_count != len(self.test_example_ids):
            raise ModelTrainingError("CONTROL_TEST_METRIC_SAMPLE_COUNT_MISMATCH")
        if not self.research_only:
            raise ModelTrainingError("CONTROL_EVALUATION_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("CONTROL_EVALUATION_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING")

    @property
    def control_evaluation_id(self) -> str:
        return _sha(
            {
                "role": self.role.value,
                "model_id": self.model_id,
                "strategy_version": self.strategy_version,
                "source_path": self.source_path,
                "source_blob_sha": self.source_blob_sha,
                "process_orders_on_close": self.process_orders_on_close,
                "dataset_id": self.dataset_id,
                "fold_id": self.fold_id,
                "test_example_ids": self.test_example_ids,
                "test_evidence_sha256": self.test_evidence_sha256,
                "metrics": _metrics_payload(self.metrics),
            }
        )


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """Candidate minus control. Negative max-drawdown delta means less drawdown."""

    hit_rate: float
    expectancy_r: float
    profit_factor: float | None
    cumulative_r: float
    max_drawdown_r: float


@dataclass(frozen=True, slots=True)
class ResearchControlBenchmark:
    """Deterministic post-TEST comparison; never a promotion or execution decision."""

    dataset_id: str
    fold_id: str
    selected_specification_id: str
    selected_artifact_sha256: str
    test_example_ids: tuple[str, ...]
    test_evidence_sha256: str
    candidate_metrics: OutOfSampleMetrics
    sh24_control: FrozenControlEvaluation
    sh25_control: FrozenControlEvaluation
    sh24_delta: MetricDelta
    sh25_delta: MetricDelta
    test_influenced_selection: bool = False
    retuning_authorized: bool = False
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False
    research_only: bool = True

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.fold_id.strip():
            raise ModelTrainingError("BENCHMARK_DATASET_AND_FOLD_REQUIRED")
        if not self.selected_specification_id.strip():
            raise ModelTrainingError("BENCHMARK_SPECIFICATION_ID_REQUIRED")
        _require_sha256(self.selected_artifact_sha256, "BENCHMARK_ARTIFACT_SHA256")
        _require_example_ids(self.test_example_ids, "BENCHMARK_TEST")
        _require_sha256(self.test_evidence_sha256, "BENCHMARK_TEST_EVIDENCE_SHA256")
        if self.candidate_metrics.sample_count != len(self.test_example_ids):
            raise ModelTrainingError("BENCHMARK_TEST_METRIC_SAMPLE_COUNT_MISMATCH")

        if self.sh24_control.role is not ControlRole.SH24_CONTROL:
            raise ModelTrainingError("SH24_CONTROL_REQUIRED")
        if self.sh25_control.role is not ControlRole.SH25_CHALLENGER:
            raise ModelTrainingError("SH25_CHALLENGER_REQUIRED")
        for control in (self.sh24_control, self.sh25_control):
            if control.dataset_id != self.dataset_id:
                raise ModelTrainingError("CONTROL_BENCHMARK_DATASET_ID_MISMATCH")
            if control.fold_id != self.fold_id:
                raise ModelTrainingError("CONTROL_BENCHMARK_FOLD_ID_MISMATCH")
            if control.test_example_ids != self.test_example_ids:
                raise ModelTrainingError("CONTROL_BENCHMARK_TEST_COHORT_MISMATCH")
            if control.test_evidence_sha256 != self.test_evidence_sha256:
                raise ModelTrainingError("CONTROL_BENCHMARK_TEST_EVIDENCE_MISMATCH")

        if self.sh24_delta != _metric_delta(self.candidate_metrics, self.sh24_control.metrics):
            raise ModelTrainingError("SH24_BENCHMARK_DELTA_MISMATCH")
        if self.sh25_delta != _metric_delta(self.candidate_metrics, self.sh25_control.metrics):
            raise ModelTrainingError("SH25_BENCHMARK_DELTA_MISMATCH")
        if self.test_influenced_selection or self.retuning_authorized:
            raise ModelTrainingError("TEST_BENCHMARK_CANNOT_INFLUENCE_SELECTION_OR_RETUNING")
        if not self.research_only:
            raise ModelTrainingError("CONTROL_BENCHMARK_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("CONTROL_BENCHMARK_CANNOT_AUTHORIZE_PROMOTION_OR_TRADING")

    @property
    def benchmark_id(self) -> str:
        return _sha(
            {
                "dataset_id": self.dataset_id,
                "fold_id": self.fold_id,
                "selected_specification_id": self.selected_specification_id,
                "selected_artifact_sha256": self.selected_artifact_sha256,
                "test_example_ids": self.test_example_ids,
                "test_evidence_sha256": self.test_evidence_sha256,
                "candidate_metrics": _metrics_payload(self.candidate_metrics),
                "sh24_control_evaluation_id": self.sh24_control.control_evaluation_id,
                "sh25_control_evaluation_id": self.sh25_control.control_evaluation_id,
                "sh24_delta": _delta_payload(self.sh24_delta),
                "sh25_delta": _delta_payload(self.sh25_delta),
            }
        )


def compare_against_frozen_controls(
    *,
    candidate: FinalTestEvaluation,
    candidate_test_evidence_sha256: str,
    sh24_control: FrozenControlEvaluation,
    sh25_control: FrozenControlEvaluation,
) -> ResearchControlBenchmark:
    """Bind candidate, SH24, and SH25 to one immutable TEST evidence cohort.

    This function intentionally accepts only a ``FinalTestEvaluation``. Validation
    selection must already be frozen, and the final TEST must already be untouched.
    The resulting comparison has no fitting, selection, promotion, PAPER, or trading
    authority.
    """

    if candidate.selection.test_metrics_observed:
        raise ModelTrainingError("TEST_DATA_CANNOT_INFLUENCE_VALIDATION_SELECTION")
    if candidate.retuned_after_test:
        raise ModelTrainingError("MODEL_CANNOT_BE_RETUNED_AFTER_FINAL_TEST")
    _require_sha256(candidate_test_evidence_sha256, "CANDIDATE_TEST_EVIDENCE_SHA256")

    return ResearchControlBenchmark(
        dataset_id=candidate.dataset_id,
        fold_id=candidate.fold_id,
        selected_specification_id=candidate.selected_specification_id,
        selected_artifact_sha256=candidate.selected_artifact_sha256,
        test_example_ids=candidate.test_example_ids,
        test_evidence_sha256=candidate_test_evidence_sha256,
        candidate_metrics=candidate.metrics,
        sh24_control=sh24_control,
        sh25_control=sh25_control,
        sh24_delta=_metric_delta(candidate.metrics, sh24_control.metrics),
        sh25_delta=_metric_delta(candidate.metrics, sh25_control.metrics),
    )


def _metric_delta(candidate: OutOfSampleMetrics, control: OutOfSampleMetrics) -> MetricDelta:
    profit_factor = None
    if candidate.profit_factor is not None and control.profit_factor is not None:
        profit_factor = candidate.profit_factor - control.profit_factor
    return MetricDelta(
        hit_rate=candidate.hit_rate - control.hit_rate,
        expectancy_r=candidate.expectancy_r - control.expectancy_r,
        profit_factor=profit_factor,
        cumulative_r=candidate.cumulative_r - control.cumulative_r,
        max_drawdown_r=candidate.max_drawdown_r - control.max_drawdown_r,
    )


def _metrics_payload(metrics: OutOfSampleMetrics) -> dict[str, object]:
    return {
        "sample_count": metrics.sample_count,
        "hit_rate": metrics.hit_rate,
        "expectancy_r": metrics.expectancy_r,
        "profit_factor": metrics.profit_factor,
        "cumulative_r": metrics.cumulative_r,
        "max_drawdown_r": metrics.max_drawdown_r,
    }


def _delta_payload(delta: MetricDelta) -> dict[str, object]:
    return {
        "hit_rate": delta.hit_rate,
        "expectancy_r": delta.expectancy_r,
        "profit_factor": delta.profit_factor,
        "cumulative_r": delta.cumulative_r,
        "max_drawdown_r": delta.max_drawdown_r,
    }


def _require_example_ids(values: tuple[str, ...], prefix: str) -> None:
    if not values:
        raise ModelTrainingError(f"{prefix}_EXAMPLE_IDS_REQUIRED")
    if any(not value.strip() for value in values):
        raise ModelTrainingError(f"{prefix}_EXAMPLE_IDS_INVALID")
    if len(set(values)) != len(values):
        raise ModelTrainingError(f"{prefix}_EXAMPLE_IDS_MUST_BE_UNIQUE")


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64:
        raise ModelTrainingError(f"{field}_INVALID")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ModelTrainingError(f"{field}_INVALID") from exc


def _sha(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "SH24_CONTROL_IDENTITY",
    "SH25_CHALLENGER_IDENTITY",
    "ControlRole",
    "FrozenControlEvaluation",
    "FrozenControlIdentity",
    "MetricDelta",
    "ResearchControlBenchmark",
    "compare_against_frozen_controls",
]
