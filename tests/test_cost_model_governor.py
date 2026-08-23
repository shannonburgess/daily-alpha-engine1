from datetime import UTC, datetime

import pytest

from daily_alpha.cost_model_governor import (
    ComputeKind,
    CostModelGovernor,
    CostModelGovernorError,
    DecisionCriticality,
    FinOpsMetrics,
    InformationClassification,
    IntelligenceCacheIdentity,
    ModelCandidate,
    ModelCapability,
    RoutingState,
    TaskRequirement,
)


AS_OF = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)


def _candidate(
    candidate_id: str,
    *,
    cost: float,
    quality: float,
    latency: float = 600.0,
    reliability: float = 0.995,
    compute_kind: ComputeKind = ComputeKind.LLM,
    capabilities: tuple[ModelCapability, ...] = (
        ModelCapability.REASONING,
        ModelCapability.STRUCTURED_OUTPUT,
    ),
    information_classes: tuple[InformationClassification, ...] = (
        InformationClassification.PUBLIC,
        InformationClassification.INTERNAL,
    ),
) -> ModelCandidate:
    return ModelCandidate(
        candidate_id=candidate_id,
        provider="TEST",
        model_id=candidate_id,
        model_version="1",
        compute_kind=compute_kind,
        capabilities=capabilities,
        supported_information_classes=information_classes,
        quality_score=quality,
        p95_latency_ms=latency,
        reliability_score=reliability,
        estimated_cost_per_call_usd=cost,
    )


def _requirement(**overrides) -> TaskRequirement:
    payload = {
        "task_id": "CIO-FUSION-1",
        "required_capabilities": (
            ModelCapability.REASONING,
            ModelCapability.STRUCTURED_OUTPUT,
        ),
        "information_classification": InformationClassification.INTERNAL,
        "min_quality_score": 0.85,
        "max_p95_latency_ms": 2_000.0,
        "min_reliability_score": 0.99,
        "criticality": DecisionCriticality.HIGH,
    }
    payload.update(overrides)
    return TaskRequirement(**payload)


def test_governor_selects_lowest_cost_candidate_only_after_quality_filters() -> None:
    governor = CostModelGovernor()
    cheap_but_weak = _candidate("cheap", cost=0.01, quality=0.70)
    qualified_mid = _candidate("mid", cost=0.04, quality=0.88)
    qualified_premium = _candidate("premium", cost=0.20, quality=0.98)

    decision = governor.route(
        _requirement(),
        (cheap_but_weak, qualified_mid, qualified_premium),
    )

    assert decision.state is RoutingState.SELECTED
    assert decision.selected_candidate_id == "mid"
    assert decision.estimated_cost_per_call_usd == 0.04
    assert decision.quality_floor_preserved is True
    rejected = {item.candidate_id: item.reasons for item in decision.rejections}
    assert "QUALITY_BELOW_FLOOR" in rejected["cheap"]


def test_no_candidate_causes_explicit_escalation_not_quality_downgrade() -> None:
    decision = CostModelGovernor().route(
        _requirement(min_quality_score=0.99),
        (
            _candidate("cheap", cost=0.01, quality=0.70),
            _candidate("premium", cost=0.20, quality=0.98),
        ),
    )

    assert decision.state is RoutingState.ESCALATION_REQUIRED
    assert decision.selected_candidate_id is None
    assert decision.eligible_candidate_ids == ()
    assert decision.reason == "NO_ELIGIBLE_CANDIDATE_ESCALATE_WITHOUT_QUALITY_DOWNGRADE"


def test_exact_calculation_can_require_deterministic_compute() -> None:
    deterministic = _candidate(
        "python-risk-engine",
        cost=0.0,
        quality=1.0,
        latency=25.0,
        compute_kind=ComputeKind.DETERMINISTIC,
        capabilities=(ModelCapability.EXACT_CALCULATION,),
    )
    llm = _candidate(
        "llm-math",
        cost=0.02,
        quality=0.99,
        capabilities=(ModelCapability.EXACT_CALCULATION,),
    )
    requirement = TaskRequirement(
        task_id="PORTFOLIO-BETA",
        required_capabilities=(ModelCapability.EXACT_CALCULATION,),
        information_classification=InformationClassification.INTERNAL,
        min_quality_score=0.99,
        max_p95_latency_ms=1_000.0,
        min_reliability_score=0.99,
        deterministic_required=True,
    )

    decision = CostModelGovernor().route(requirement, (llm, deterministic))

    assert decision.selected_candidate_id == "python-risk-engine"
    rejected = {item.candidate_id: item.reasons for item in decision.rejections}
    assert "DETERMINISTIC_COMPUTE_REQUIRED" in rejected["llm-math"]


def test_information_classification_must_be_explicitly_supported() -> None:
    public_only = _candidate(
        "public-only",
        cost=0.01,
        quality=0.95,
        information_classes=(InformationClassification.PUBLIC,),
    )
    restricted = _candidate(
        "restricted-approved",
        cost=0.10,
        quality=0.95,
        information_classes=(
            InformationClassification.PUBLIC,
            InformationClassification.INTERNAL,
            InformationClassification.CONFIDENTIAL,
            InformationClassification.MNPI_RESTRICTED,
        ),
    )
    requirement = _requirement(
        information_classification=InformationClassification.MNPI_RESTRICTED
    )

    decision = CostModelGovernor().route(requirement, (public_only, restricted))

    assert decision.selected_candidate_id == "restricted-approved"
    rejected = {item.candidate_id: item.reasons for item in decision.rejections}
    assert "INFORMATION_CLASS_NOT_SUPPORTED" in rejected["public-only"]


def test_cache_identity_reuses_unchanged_governed_inputs_independent_of_evidence_order() -> None:
    first = IntelligenceCacheIdentity(
        as_of=AS_OF,
        task_id="SEC-AGENT-10Q",
        evidence_ids=("filing-10q", "market-context"),
        model_id="model-a",
        model_version="2026-08",
        prompt_id="sec-material-change",
        prompt_version="3",
        policy_id="research-policy",
        policy_version="7",
    )
    second = IntelligenceCacheIdentity(
        as_of=AS_OF,
        task_id="SEC-AGENT-10Q",
        evidence_ids=("market-context", "filing-10q"),
        model_id="model-a",
        model_version="2026-08",
        prompt_id="sec-material-change",
        prompt_version="3",
        policy_id="research-policy",
        policy_version="7",
    )

    assert first.cache_key == second.cache_key


def test_cache_identity_changes_when_prompt_version_changes() -> None:
    base = IntelligenceCacheIdentity(
        as_of=AS_OF,
        task_id="NEWS-AGENT",
        evidence_ids=("news-batch-1",),
        model_id="small-model",
        model_version="1",
        prompt_id="news-classifier",
        prompt_version="1",
        policy_id="news-policy",
        policy_version="1",
    )
    changed = IntelligenceCacheIdentity(
        as_of=AS_OF,
        task_id="NEWS-AGENT",
        evidence_ids=("news-batch-1",),
        model_id="small-model",
        model_version="1",
        prompt_id="news-classifier",
        prompt_version="2",
        policy_id="news-policy",
        policy_version="1",
    )

    assert base.cache_key != changed.cache_key


def test_finops_metrics_capture_decision_level_economics() -> None:
    metrics = FinOpsMetrics(
        as_of=AS_OF,
        cost_per_agent_run_usd=0.012,
        cost_per_recommendation_usd=0.08,
        cost_per_customer_usd=4.5,
        llm_cost_per_revenue_dollar=0.03,
        data_cost_per_active_user_usd=1.2,
        aws_cost_per_1000_opportunities_usd=3.4,
        premium_model_escalation_rate=0.08,
        cache_hit_rate=0.72,
        cost_by_agent_usd={"SEC": 0.01, "CIO": 0.19},
        quality_score_by_model={"SMALL": 0.88, "PREMIUM": 0.97},
    )

    assert dict(metrics.cost_by_agent_usd)["CIO"] == 0.19
    assert dict(metrics.quality_score_by_model)["PREMIUM"] == 0.97


def test_finops_metrics_reject_invalid_cache_rate() -> None:
    with pytest.raises(CostModelGovernorError, match="CACHE_HIT_RATE_OUT_OF_RANGE"):
        FinOpsMetrics(
            as_of=AS_OF,
            cost_per_agent_run_usd=0.0,
            cost_per_recommendation_usd=0.0,
            cost_per_customer_usd=0.0,
            llm_cost_per_revenue_dollar=0.0,
            data_cost_per_active_user_usd=0.0,
            aws_cost_per_1000_opportunities_usd=0.0,
            premium_model_escalation_rate=0.0,
            cache_hit_rate=1.1,
        )
