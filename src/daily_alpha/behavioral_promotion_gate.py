"""Fail-closed promotion-readiness gate for Behavioral Change research.

This module does not promote a factor.  It only decides whether a frozen, point-in-time
holdout evidence package is complete enough to enter the separate model-governance
review.  Even a fully satisfied result keeps promotion/trading/live authorization false.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from .behavioral_orthogonality import CoreFactorFamily, OrthogonalityDiagnostic
from .behavioral_validation import LeadLagObservation, SourceAblationResult


@dataclass(frozen=True)
class BehavioralValidationWindow:
    development_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    evaluation_cutoff: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("development_end", self.development_end),
            ("holdout_start", self.holdout_start),
            ("holdout_end", self.holdout_end),
            ("evaluation_cutoff", self.evaluation_cutoff),
        ):
            _require_aware(value, name)
        development_end = self.development_end.astimezone(UTC)
        holdout_start = self.holdout_start.astimezone(UTC)
        holdout_end = self.holdout_end.astimezone(UTC)
        cutoff = self.evaluation_cutoff.astimezone(UTC)
        if development_end >= holdout_start:
            raise ValueError("BEHAVIORAL_DEVELOPMENT_HOLDOUT_OVERLAP")
        if holdout_start > holdout_end:
            raise ValueError("BEHAVIORAL_HOLDOUT_WINDOW_INVALID")
        if cutoff < holdout_start or cutoff > holdout_end:
            raise ValueError("BEHAVIORAL_EVALUATION_CUTOFF_OUTSIDE_HOLDOUT")


@dataclass(frozen=True)
class BehavioralPromotionCriteria:
    min_holdout_dates: int
    min_lead_lag_observations: int
    min_behavior_lead_fraction: float
    max_single_source_score_delta: float
    min_forward_outcome_observations: int
    min_rank_ic: float
    min_forward_return_spread: float
    max_false_positive_rate: float

    def __post_init__(self) -> None:
        if self.min_holdout_dates <= 0:
            raise ValueError("min_holdout_dates must be positive")
        if self.min_lead_lag_observations <= 0:
            raise ValueError("min_lead_lag_observations must be positive")
        if not 0.0 <= self.min_behavior_lead_fraction <= 1.0:
            raise ValueError("min_behavior_lead_fraction must be in [0, 1]")
        if self.max_single_source_score_delta < 0.0:
            raise ValueError("max_single_source_score_delta must be non-negative")
        if self.min_forward_outcome_observations <= 0:
            raise ValueError("min_forward_outcome_observations must be positive")
        if not -1.0 <= self.min_rank_ic <= 1.0:
            raise ValueError("min_rank_ic must be in [-1, 1]")
        if not 0.0 <= self.max_false_positive_rate <= 1.0:
            raise ValueError("max_false_positive_rate must be in [0, 1]")
        for name, value in (
            ("max_single_source_score_delta", self.max_single_source_score_delta),
            ("min_forward_return_spread", self.min_forward_return_spread),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class BehavioralHoldoutOutcomeEvidence:
    evaluation_cutoff: datetime
    observations: int
    rank_ic: float | None
    forward_return_spread: float | None
    false_positive_rate: float | None
    evidence_id: str
    point_in_time: bool = True
    development_data_excluded: bool = True
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.evaluation_cutoff, "evaluation_cutoff")
        if self.observations < 0:
            raise ValueError("observations must be non-negative")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")
        if self.rank_ic is not None and (
            not math.isfinite(self.rank_ic) or not -1.0 <= self.rank_ic <= 1.0
        ):
            raise ValueError("rank_ic must be finite and in [-1, 1]")
        if self.forward_return_spread is not None and not math.isfinite(
            self.forward_return_spread
        ):
            raise ValueError("forward_return_spread must be finite")
        if self.false_positive_rate is not None and (
            not math.isfinite(self.false_positive_rate)
            or not 0.0 <= self.false_positive_rate <= 1.0
        ):
            raise ValueError("false_positive_rate must be finite and in [0, 1]")


@dataclass(frozen=True)
class BehavioralPromotionReadiness:
    status: str
    reasons: tuple[str, ...]
    holdout_dates: int
    complete_ablation_dates: int
    lead_lag_observations: int
    behavior_lead_fraction: float | None
    orthogonality_families_complete: int
    forward_outcome_observations: int
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def evaluate_behavioral_promotion_readiness(
    *,
    window: BehavioralValidationWindow,
    criteria: BehavioralPromotionCriteria,
    holdout_dates: tuple[date, ...],
    source_ablation_by_date: tuple[tuple[SourceAblationResult, ...], ...],
    lead_lag: tuple[LeadLagObservation, ...],
    orthogonality: tuple[OrthogonalityDiagnostic, ...],
    outcomes: BehavioralHoldoutOutcomeEvidence,
) -> BehavioralPromotionReadiness:
    """Evaluate whether evidence is complete enough for governance review.

    ``READY_FOR_GOVERNANCE_REVIEW`` is not a promotion.  The returned object always
    preserves ``promotion_authorized=false`` and both trading/live safety flags false.
    """
    _validate_safety(source_ablation_by_date, lead_lag, orthogonality, outcomes)
    cutoff = window.evaluation_cutoff.astimezone(UTC)
    holdout_start = window.holdout_start.astimezone(UTC).date()
    cutoff_date = cutoff.date()

    unique_dates = tuple(sorted(set(holdout_dates)))
    if len(unique_dates) != len(holdout_dates):
        raise ValueError("BEHAVIORAL_DUPLICATE_HOLDOUT_DATE")
    if len(source_ablation_by_date) != len(unique_dates):
        raise ValueError("BEHAVIORAL_ABLATION_DATE_COUNT_MISMATCH")
    for day in unique_dates:
        if day < holdout_start or day > cutoff_date:
            raise ValueError("BEHAVIORAL_HOLDOUT_DATE_OUTSIDE_EVALUATED_WINDOW")

    reasons: set[str] = set()
    if len(unique_dates) < criteria.min_holdout_dates:
        reasons.add("INSUFFICIENT_HOLDOUT_DATES")

    complete_ablation_dates = 0
    for rows in source_ablation_by_date:
        if not rows:
            reasons.add("SOURCE_ABLATION_MISSING")
            continue
        if any(row.status != "COMPLETE" or row.score_delta is None for row in rows):
            reasons.add("SOURCE_ABLATION_INCOMPLETE")
            continue
        complete_ablation_dates += 1
        if any(
            abs(row.score_delta) > criteria.max_single_source_score_delta
            for row in rows
            if row.score_delta is not None
        ):
            reasons.add("SOURCE_CONCENTRATION_RISK")
    if complete_ablation_dates < criteria.min_holdout_dates:
        reasons.add("INSUFFICIENT_COMPLETE_ABLATION_DATES")

    eligible_lead_lag = tuple(
        row
        for row in lead_lag
        if window.holdout_start.astimezone(UTC)
        <= row.behavioral_as_of.astimezone(UTC)
        <= cutoff
        and row.recognition_known_at.astimezone(UTC) <= cutoff
    )
    if len(eligible_lead_lag) < criteria.min_lead_lag_observations:
        reasons.add("INSUFFICIENT_LEAD_LAG_EVIDENCE")
        behavior_lead_fraction = None
    else:
        behavior_leads = sum(
            row.relationship == "BEHAVIOR_LEADS_RECOGNITION" for row in eligible_lead_lag
        )
        behavior_lead_fraction = behavior_leads / len(eligible_lead_lag)
        if behavior_lead_fraction < criteria.min_behavior_lead_fraction:
            reasons.add("LEAD_LAG_NOT_SUPPORTIVE")

    by_family: dict[CoreFactorFamily, OrthogonalityDiagnostic] = {}
    for row in orthogonality:
        if row.evaluation_cutoff.astimezone(UTC) != cutoff:
            raise ValueError("BEHAVIORAL_ORTHOGONALITY_CUTOFF_MISMATCH")
        prior = by_family.get(row.family)
        if prior is not None and prior != row:
            raise ValueError("CONFLICTING_DUPLICATE_ORTHOGONALITY_FAMILY")
        by_family[row.family] = row
    complete_families = 0
    for family in CoreFactorFamily:
        row = by_family.get(family)
        if row is None:
            reasons.add("ORTHOGONALITY_FAMILY_MISSING")
            continue
        if row.redundancy_risk is True or row.status == "REDUNDANCY_RISK":
            reasons.add("CORE_FACTOR_REDUNDANCY_RISK")
            continue
        if row.redundancy_risk is None or row.status != "ORTHOGONALITY_NOT_REJECTED":
            reasons.add("ORTHOGONALITY_EVIDENCE_INCOMPLETE")
            continue
        complete_families += 1
    if complete_families != len(CoreFactorFamily):
        reasons.add("ORTHOGONALITY_NOT_FULLY_VALIDATED")

    if outcomes.evaluation_cutoff.astimezone(UTC) != cutoff:
        raise ValueError("BEHAVIORAL_OUTCOME_CUTOFF_MISMATCH")
    if not outcomes.point_in_time:
        reasons.add("OUTCOME_EVIDENCE_NOT_POINT_IN_TIME")
    if not outcomes.development_data_excluded:
        reasons.add("DEVELOPMENT_DATA_LEAKAGE_RISK")
    if outcomes.observations < criteria.min_forward_outcome_observations:
        reasons.add("INSUFFICIENT_FORWARD_OUTCOME_EVIDENCE")
    if outcomes.rank_ic is None or outcomes.rank_ic < criteria.min_rank_ic:
        reasons.add("RANK_IC_THRESHOLD_NOT_MET")
    if (
        outcomes.forward_return_spread is None
        or outcomes.forward_return_spread < criteria.min_forward_return_spread
    ):
        reasons.add("FORWARD_RETURN_SPREAD_THRESHOLD_NOT_MET")
    if (
        outcomes.false_positive_rate is None
        or outcomes.false_positive_rate > criteria.max_false_positive_rate
    ):
        reasons.add("FALSE_POSITIVE_RATE_THRESHOLD_NOT_MET")

    ordered_reasons = tuple(sorted(reasons))
    return BehavioralPromotionReadiness(
        status=(
            "READY_FOR_GOVERNANCE_REVIEW"
            if not ordered_reasons
            else "EVIDENCE_INCOMPLETE_OR_REJECTED"
        ),
        reasons=ordered_reasons,
        holdout_dates=len(unique_dates),
        complete_ablation_dates=complete_ablation_dates,
        lead_lag_observations=len(eligible_lead_lag),
        behavior_lead_fraction=(
            None if behavior_lead_fraction is None else round(behavior_lead_fraction, 6)
        ),
        orthogonality_families_complete=complete_families,
        forward_outcome_observations=outcomes.observations,
    )


def _validate_safety(
    source_ablation_by_date: tuple[tuple[SourceAblationResult, ...], ...],
    lead_lag: tuple[LeadLagObservation, ...],
    orthogonality: tuple[OrthogonalityDiagnostic, ...],
    outcomes: BehavioralHoldoutOutcomeEvidence,
) -> None:
    rows = [
        *[row for group in source_ablation_by_date for row in group],
        *lead_lag,
        *orthogonality,
        outcomes,
    ]
    for row in rows:
        if getattr(row, "research_only", None) is not True:
            raise ValueError("BEHAVIORAL_PROMOTION_RESEARCH_ONLY_REQUIRED")
        if getattr(row, "trading_authorized", None) is not False:
            raise ValueError("BEHAVIORAL_PROMOTION_TRADING_AUTHORIZATION_REJECTED")
        if getattr(row, "live_trading_enabled", None) is not False:
            raise ValueError("BEHAVIORAL_PROMOTION_LIVE_TRADING_REJECTED")
    for row in (*orthogonality, outcomes):
        if getattr(row, "promotion_authorized", None) is not False:
            raise ValueError("BEHAVIORAL_PROMOTION_AUTHORIZATION_REJECTED")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
