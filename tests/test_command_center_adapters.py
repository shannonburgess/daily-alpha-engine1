from __future__ import annotations

from datetime import UTC, datetime, timedelta

from daily_alpha.agentic.command_center import (
    CommandCenterComponentKind,
    CommandCenterEntityKind,
    InstitutionalCommandCenterBuilder,
)
from daily_alpha.agentic.command_center_adapters import (
    project_data_plane_readiness,
    project_model_governance,
    project_model_stress,
    project_provider_reliability,
)
from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.data_plane_readiness import DataPlaneReadinessSnapshot
from daily_alpha.agentic.data_providers import DataDomain, ProviderRole
from daily_alpha.agentic.model_governance import (
    ModelGovernanceAssessment,
    ModelGovernancePacket,
    ModelLifecycleStage,
)
from daily_alpha.agentic.model_stress import (
    ModelStressAssessment,
    ModelStressPacket,
    ScenarioStressAssessment,
    StressScenarioClass,
)
from daily_alpha.agentic.provider_reliability import (
    ProviderReliabilityAssessment,
    ProviderReliabilityReport,
)


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def test_data_plane_projection_preserves_warning_severity_and_source_id() -> None:
    snapshot = DataPlaneReadinessSnapshot(
        as_of=AS_OF,
        status=ReadinessStatus.WARNING,
        domains=(),
        healthy_provider_count=2,
        degraded_provider_count=1,
        stale_provider_count=0,
        unavailable_provider_count=0,
        blocked_domains=(DataDomain.BEHAVIORAL,),
        warning_domains=(DataDomain.NEWS_CATALYSTS,),
    )

    projected = project_data_plane_readiness(snapshot)

    assert projected.kind is CommandCenterComponentKind.DATA_PLANE
    assert projected.entity_kind is CommandCenterEntityKind.PLATFORM
    assert projected.status is ReadinessStatus.WARNING
    assert projected.source_record_id == snapshot.snapshot_id
    assert projected.blockers == ()
    assert "OPTIONAL_DOMAIN_BLOCKED:BEHAVIORAL" in projected.warnings
    assert projected.metrics == tuple(sorted(projected.metrics))


def test_provider_reliability_projection_emits_domain_and_provider_scorecards() -> None:
    assessment = ProviderReliabilityAssessment(
        provider_id="MASSIVE",
        independence_group="MASSIVE_MARKET_DATA",
        role=ProviderRole.PRIMARY,
        status=ReadinessStatus.WARNING,
        runtime_sample_count=2,
        healthy_runtime_count=2,
        healthy_ratio=1.0,
        observation_count=4,
        eligible_observation_count=4,
        excluded_observation_count=0,
        exclusion_ratio=0.0,
        incident_ids=("1" * 64,),
        blockers=(),
        warnings=("INSUFFICIENT_RUNTIME_HISTORY",),
    )
    report = ProviderReliabilityReport(
        domain=DataDomain.MARKET_BARS,
        as_of=AS_OF,
        window_start=AS_OF - timedelta(days=7),
        policy_id="2" * 64,
        status=ReadinessStatus.WARNING,
        provider_assessments=(assessment,),
        incidents=(),
        blockers=(),
        warnings=("PROVIDER_WARNING:MASSIVE",),
    )

    projected = project_provider_reliability(report)

    assert len(projected) == 2
    aggregate, provider = projected
    assert aggregate.source_record_id == report.report_id
    assert aggregate.status is ReadinessStatus.WARNING
    assert provider.entity_kind is CommandCenterEntityKind.PROVIDER
    assert provider.entity_id == "MASSIVE"
    assert provider.source_record_id == assessment.assessment_id
    assert provider.lineage_ids == ("1" * 64,)


def test_model_governance_projection_preserves_eligibility_lineage() -> None:
    assessment = ModelGovernanceAssessment(
        model_view_id="3" * 64,
        model_id="SH24",
        model_version="v2.4",
        definition_id="4" * 64,
        lifecycle_stage=ModelLifecycleStage.SHADOW,
        validation_id="5" * 64,
        status=ReadinessStatus.PASS,
        blockers=(),
        warnings=(),
        eligible_for_cio_research=True,
    )
    packet = ModelGovernancePacket(
        security_id="MU",
        as_of=AS_OF,
        registry_id="6" * 64,
        policy_id="7" * 64,
        assessments=(assessment,),
        eligible_model_view_ids=(assessment.model_view_id,),
        status=ReadinessStatus.PASS,
        blockers=(),
        warnings=(),
    )

    aggregate, model = project_model_governance(packet)

    assert aggregate.source_record_id == packet.packet_id
    assert aggregate.security_id == "MU"
    assert model.entity_id == "SH24:V2.4"
    assert model.status is ReadinessStatus.PASS
    assert assessment.validation_id in model.lineage_ids
    assert dict(model.metrics)["eligible_for_cio_research"] is True


def test_model_stress_projection_preserves_robustness_and_governance_lineage() -> None:
    scenario = ScenarioStressAssessment(
        scenario_definition_id="8" * 64,
        stress_result_id="9" * 64,
        scenario_class=StressScenarioClass.HISTORICAL_SHOCK,
        passed=True,
        reasons=(),
    )
    assessment = ModelStressAssessment(
        model_view_id="a" * 64,
        model_id="SH24",
        model_version="v2.4",
        upstream_governance_assessment_id="b" * 64,
        scenario_assessments=(scenario,),
        covered_classes=(StressScenarioClass.HISTORICAL_SHOCK,),
        pass_ratio=1.0,
        status=ReadinessStatus.PASS,
        blockers=(),
        warnings=(),
        stress_qualified_for_cio_research=True,
    )
    packet = ModelStressPacket(
        security_id="MU",
        as_of=AS_OF,
        upstream_governance_packet_id="c" * 64,
        scenario_registry_id="d" * 64,
        policy_id="e" * 64,
        assessments=(assessment,),
        stress_qualified_model_view_ids=(assessment.model_view_id,),
        status=ReadinessStatus.PASS,
        blockers=(),
        warnings=(),
    )

    aggregate, model = project_model_stress(packet)
    snapshot = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(model, aggregate),
        security_id="MU",
    )

    assert aggregate.source_record_id == packet.packet_id
    assert packet.upstream_governance_packet_id in aggregate.lineage_ids
    assert dict(model.metrics)["pass_ratio"] == 1.0
    assert scenario.assessment_id in model.lineage_ids
    assert snapshot.status is ReadinessStatus.PASS
    assert snapshot.pass_count == 2


def test_typed_projection_layer_remains_read_only() -> None:
    snapshot = DataPlaneReadinessSnapshot(
        as_of=AS_OF,
        status=ReadinessStatus.PASS,
        domains=(),
        healthy_provider_count=2,
        degraded_provider_count=0,
        stale_provider_count=0,
        unavailable_provider_count=0,
        blocked_domains=(),
        warning_domains=(),
    )

    projected = project_data_plane_readiness(snapshot)

    assert projected.research_only is True
    assert projected.paper_ledger_mutation_authorized is False
    assert projected.portfolio_construction_authorized is False
    assert projected.execution_authorized is False
    assert projected.trading_authorized is False
    assert projected.live_trading_enabled is False
