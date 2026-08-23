"""Deterministic cost-aware compute routing for ConvexRidge intelligence workloads.

The Cost & Model Governor does not call an LLM, authorize capital, or execute trades. It
selects the lowest-cost eligible compute candidate only after required quality, latency,
reliability, capability, information-handling, and deterministic-compute constraints have
been satisfied. If no candidate clears those floors, the result explicitly escalates rather
than silently degrading quality.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CostModelGovernorError(ValueError):
    """A cost/model-governance contract violated a deterministic invariant."""


class ComputeKind(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM = "LLM"


class InformationClassification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    MNPI_RESTRICTED = "MNPI_RESTRICTED"


class ModelCapability(StrEnum):
    EXTRACTION = "EXTRACTION"
    CLASSIFICATION = "CLASSIFICATION"
    SUMMARIZATION = "SUMMARIZATION"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    REASONING = "REASONING"
    MULTI_MODEL_SYNTHESIS = "MULTI_MODEL_SYNTHESIS"
    EXACT_CALCULATION = "EXACT_CALCULATION"
    RULE_EVALUATION = "RULE_EVALUATION"


class DecisionCriticality(StrEnum):
    ROUTINE = "ROUTINE"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    MATERIAL = "MATERIAL"


class RoutingState(StrEnum):
    SELECTED = "SELECTED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


@dataclass(frozen=True)
class ModelCandidate:
    """One eligible compute implementation exposed to the model router."""

    candidate_id: str
    provider: str
    model_id: str
    model_version: str
    compute_kind: ComputeKind
    capabilities: tuple[ModelCapability, ...]
    supported_information_classes: tuple[InformationClassification, ...]
    quality_score: float
    p95_latency_ms: float
    reliability_score: float
    estimated_cost_per_call_usd: float
    enabled: bool = True

    def __post_init__(self) -> None:
        candidate_id = _required(self.candidate_id, "CANDIDATE_ID")
        provider = _required(self.provider, "PROVIDER")
        model_id = _required(self.model_id, "MODEL_ID")
        model_version = _required(self.model_version, "MODEL_VERSION")
        capabilities = tuple(sorted(set(self.capabilities), key=lambda item: item.value))
        information_classes = tuple(
            sorted(set(self.supported_information_classes), key=lambda item: item.value)
        )
        if not capabilities:
            raise CostModelGovernorError("CANDIDATE_CAPABILITY_REQUIRED")
        if not information_classes:
            raise CostModelGovernorError("CANDIDATE_INFORMATION_CLASS_REQUIRED")
        _fraction(self.quality_score, "CANDIDATE_QUALITY")
        _nonnegative(self.p95_latency_ms, "CANDIDATE_LATENCY")
        _fraction(self.reliability_score, "CANDIDATE_RELIABILITY")
        _nonnegative(self.estimated_cost_per_call_usd, "CANDIDATE_COST")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", model_version)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "supported_information_classes", information_classes)


@dataclass(frozen=True)
class TaskRequirement:
    """Quality/security/latency floors that cost optimization may never undercut."""

    task_id: str
    required_capabilities: tuple[ModelCapability, ...]
    information_classification: InformationClassification
    min_quality_score: float
    max_p95_latency_ms: float
    min_reliability_score: float
    criticality: DecisionCriticality = DecisionCriticality.STANDARD
    deterministic_required: bool = False

    def __post_init__(self) -> None:
        task_id = _required(self.task_id, "TASK_ID")
        capabilities = tuple(sorted(set(self.required_capabilities), key=lambda item: item.value))
        if not capabilities:
            raise CostModelGovernorError("TASK_CAPABILITY_REQUIRED")
        _fraction(self.min_quality_score, "TASK_MIN_QUALITY")
        _nonnegative(self.max_p95_latency_ms, "TASK_MAX_LATENCY")
        _fraction(self.min_reliability_score, "TASK_MIN_RELIABILITY")
        if self.deterministic_required and not any(
            capability in {ModelCapability.EXACT_CALCULATION, ModelCapability.RULE_EVALUATION}
            for capability in capabilities
        ):
            raise CostModelGovernorError("DETERMINISTIC_TASK_REQUIRES_EXACT_OR_RULE_CAPABILITY")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "required_capabilities", capabilities)


@dataclass(frozen=True)
class CandidateRejection:
    candidate_id: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _required(self.candidate_id, "CANDIDATE_ID"))
        reasons = tuple(sorted({_required(reason, "REJECTION_REASON") for reason in self.reasons}))
        if not reasons:
            raise CostModelGovernorError("CANDIDATE_REJECTION_REASON_REQUIRED")
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True)
class RoutingDecision:
    task_id: str
    state: RoutingState
    selected_candidate_id: str | None
    eligible_candidate_ids: tuple[str, ...]
    rejections: tuple[CandidateRejection, ...]
    reason: str
    estimated_cost_per_call_usd: float | None
    quality_floor_preserved: bool = True

    def __post_init__(self) -> None:
        task_id = _required(self.task_id, "TASK_ID")
        eligible = tuple(sorted({_required(item, "ELIGIBLE_CANDIDATE_ID") for item in self.eligible_candidate_ids}))
        reason = _required(self.reason, "ROUTING_REASON")
        if self.state is RoutingState.SELECTED:
            if self.selected_candidate_id is None:
                raise CostModelGovernorError("SELECTED_ROUTE_REQUIRES_CANDIDATE")
            if self.selected_candidate_id not in eligible:
                raise CostModelGovernorError("SELECTED_CANDIDATE_MUST_BE_ELIGIBLE")
            if self.estimated_cost_per_call_usd is None:
                raise CostModelGovernorError("SELECTED_ROUTE_REQUIRES_COST")
            _nonnegative(self.estimated_cost_per_call_usd, "SELECTED_ROUTE_COST")
        else:
            if self.selected_candidate_id is not None or self.estimated_cost_per_call_usd is not None:
                raise CostModelGovernorError("ESCALATION_ROUTE_CANNOT_SELECT_CANDIDATE")
        if not self.quality_floor_preserved:
            raise CostModelGovernorError("QUALITY_FLOOR_CANNOT_BE_WAIVED")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "eligible_candidate_ids", eligible)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "rejections",
            tuple(sorted(self.rejections, key=lambda item: item.candidate_id)),
        )


class CostModelGovernor:
    """Filter for required floors first, then minimize cost among eligible candidates."""

    def route(
        self,
        requirement: TaskRequirement,
        candidates: tuple[ModelCandidate, ...],
    ) -> RoutingDecision:
        candidate_ids = [candidate.candidate_id for candidate in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise CostModelGovernorError("CANDIDATE_IDS_MUST_BE_UNIQUE")

        eligible: list[ModelCandidate] = []
        rejections: list[CandidateRejection] = []
        required_capabilities = set(requirement.required_capabilities)

        for candidate in candidates:
            reasons: list[str] = []
            if not candidate.enabled:
                reasons.append("CANDIDATE_DISABLED")
            if requirement.deterministic_required and candidate.compute_kind is not ComputeKind.DETERMINISTIC:
                reasons.append("DETERMINISTIC_COMPUTE_REQUIRED")
            if not required_capabilities.issubset(set(candidate.capabilities)):
                reasons.append("REQUIRED_CAPABILITY_MISSING")
            if requirement.information_classification not in candidate.supported_information_classes:
                reasons.append("INFORMATION_CLASS_NOT_SUPPORTED")
            if candidate.quality_score < requirement.min_quality_score:
                reasons.append("QUALITY_BELOW_FLOOR")
            if candidate.p95_latency_ms > requirement.max_p95_latency_ms:
                reasons.append("LATENCY_ABOVE_CEILING")
            if candidate.reliability_score < requirement.min_reliability_score:
                reasons.append("RELIABILITY_BELOW_FLOOR")

            if reasons:
                rejections.append(
                    CandidateRejection(candidate_id=candidate.candidate_id, reasons=tuple(reasons))
                )
            else:
                eligible.append(candidate)

        if not eligible:
            return RoutingDecision(
                task_id=requirement.task_id,
                state=RoutingState.ESCALATION_REQUIRED,
                selected_candidate_id=None,
                eligible_candidate_ids=(),
                rejections=tuple(rejections),
                reason="NO_ELIGIBLE_CANDIDATE_ESCALATE_WITHOUT_QUALITY_DOWNGRADE",
                estimated_cost_per_call_usd=None,
            )

        selected = min(
            eligible,
            key=lambda candidate: (
                candidate.estimated_cost_per_call_usd,
                -candidate.quality_score,
                candidate.p95_latency_ms,
                -candidate.reliability_score,
                candidate.candidate_id,
            ),
        )
        return RoutingDecision(
            task_id=requirement.task_id,
            state=RoutingState.SELECTED,
            selected_candidate_id=selected.candidate_id,
            eligible_candidate_ids=tuple(candidate.candidate_id for candidate in eligible),
            rejections=tuple(rejections),
            reason="LOWEST_COST_ELIGIBLE_CANDIDATE",
            estimated_cost_per_call_usd=selected.estimated_cost_per_call_usd,
        )


@dataclass(frozen=True)
class IntelligenceCacheIdentity:
    """Reusable identity for an unchanged governed intelligence computation."""

    as_of: datetime
    task_id: str
    evidence_ids: tuple[str, ...]
    model_id: str
    model_version: str
    prompt_id: str
    prompt_version: str
    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "CACHE_AS_OF")
        evidence_ids = _normalized_ids(self.evidence_ids, "EVIDENCE_ID")
        if not evidence_ids:
            raise CostModelGovernorError("CACHE_EVIDENCE_REQUIRED")
        for field_name in (
            "task_id",
            "model_id",
            "model_version",
            "prompt_id",
            "prompt_version",
            "policy_id",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name.upper()),
            )
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    @property
    def cache_key(self) -> str:
        return _hash_payload(
            {
                "as_of": self.as_of.isoformat(),
                "task_id": self.task_id,
                "evidence_ids": list(self.evidence_ids),
                "model_id": self.model_id,
                "model_version": self.model_version,
                "prompt_id": self.prompt_id,
                "prompt_version": self.prompt_version,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
            }
        )


@dataclass(frozen=True)
class FinOpsMetrics:
    """Decision-level economics for model, data, and infrastructure governance."""

    as_of: datetime
    cost_per_agent_run_usd: float
    cost_per_recommendation_usd: float
    cost_per_customer_usd: float
    llm_cost_per_revenue_dollar: float
    data_cost_per_active_user_usd: float
    aws_cost_per_1000_opportunities_usd: float
    premium_model_escalation_rate: float
    cache_hit_rate: float
    cost_by_agent_usd: tuple[tuple[str, float], ...] | dict[str, float] = field(default_factory=tuple)
    quality_score_by_model: tuple[tuple[str, float], ...] | dict[str, float] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "FINOPS_AS_OF")
        for value, field_name in (
            (self.cost_per_agent_run_usd, "COST_PER_AGENT_RUN"),
            (self.cost_per_recommendation_usd, "COST_PER_RECOMMENDATION"),
            (self.cost_per_customer_usd, "COST_PER_CUSTOMER"),
            (self.llm_cost_per_revenue_dollar, "LLM_COST_PER_REVENUE_DOLLAR"),
            (self.data_cost_per_active_user_usd, "DATA_COST_PER_ACTIVE_USER"),
            (self.aws_cost_per_1000_opportunities_usd, "AWS_COST_PER_1000_OPPORTUNITIES"),
        ):
            _nonnegative(value, field_name)
        _fraction(self.premium_model_escalation_rate, "PREMIUM_MODEL_ESCALATION_RATE")
        _fraction(self.cache_hit_rate, "CACHE_HIT_RATE")
        cost_by_agent = _normalized_metric_map(self.cost_by_agent_usd, "AGENT_COST", fraction=False)
        quality_by_model = _normalized_metric_map(
            self.quality_score_by_model,
            "MODEL_QUALITY",
            fraction=True,
        )
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "cost_by_agent_usd", cost_by_agent)
        object.__setattr__(self, "quality_score_by_model", quality_by_model)


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CostModelGovernorError(f"{field_name}_REQUIRED")
    return normalized


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CostModelGovernorError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _fraction(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise CostModelGovernorError(f"{field_name}_OUT_OF_RANGE")


def _nonnegative(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise CostModelGovernorError(f"{field_name}_INVALID")


def _normalized_ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_required(value, field_name) for value in values))
    if len(normalized) != len(set(normalized)):
        raise CostModelGovernorError(f"{field_name}_MUST_BE_UNIQUE")
    return normalized


def _normalized_metric_map(
    values: tuple[tuple[str, float], ...] | dict[str, float],
    field_name: str,
    *,
    fraction: bool,
) -> tuple[tuple[str, float], ...]:
    items = values.items() if isinstance(values, dict) else values
    normalized = tuple(sorted((_required(str(key), field_name), float(value)) for key, value in items))
    if len(normalized) != len({key for key, _ in normalized}):
        raise CostModelGovernorError(f"{field_name}_KEYS_MUST_BE_UNIQUE")
    for _, value in normalized:
        if fraction:
            _fraction(value, field_name)
        else:
            _nonnegative(value, field_name)
    return normalized


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CostModelGovernorError("VALUE_NOT_CANONICAL_JSON") from exc


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
