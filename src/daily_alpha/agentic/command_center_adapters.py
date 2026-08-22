"""Typed projections from verified institutional packets into the command center.

These adapters are intentionally read-only. They preserve upstream PASS/WARNING/BLOCKED
semantics and immutable lineage while translating verified Stage 9D-9I packet types into
the generic Stage 9J command-center contract.
"""

from __future__ import annotations

from .command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
)
from .contracts import ReadinessStatus
from .data_plane_readiness import DataPlaneReadinessSnapshot
from .model_governance import ModelGovernancePacket
from .model_performance import ModelPerformancePacket
from .model_stress import ModelStressPacket
from .provider_reliability import ProviderReliabilityReport


def _data_plane_issues(
    snapshot: DataPlaneReadinessSnapshot,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blocked_domains = tuple(item.value for item in snapshot.blocked_domains)
    warning_domains = tuple(item.value for item in snapshot.warning_domains)
    if snapshot.status is ReadinessStatus.PASS:
        return (), ()
    if snapshot.status is ReadinessStatus.WARNING:
        warnings = tuple(
            sorted(
                {
                    *(f"OPTIONAL_DOMAIN_BLOCKED:{domain}" for domain in blocked_domains),
                    *(f"DOMAIN_WARNING:{domain}" for domain in warning_domains),
                }
            )
        )
        return (), warnings or ("DATA_PLANE_WARNING",)
    blockers = tuple(sorted(f"DOMAIN_BLOCKED:{domain}" for domain in blocked_domains))
    warnings = tuple(sorted(f"DOMAIN_WARNING:{domain}" for domain in warning_domains))
    return blockers or ("DATA_PLANE_BLOCKED",), warnings


def project_data_plane_readiness(
    snapshot: DataPlaneReadinessSnapshot,
    *,
    platform_id: str = "DAILY_ALPHA",
) -> CommandCenterComponent:
    """Project one exact Stage 9D data-plane snapshot without recomputing readiness."""
    blockers, warnings = _data_plane_issues(snapshot)
    return CommandCenterComponent(
        kind=CommandCenterComponentKind.DATA_PLANE,
        entity_kind=CommandCenterEntityKind.PLATFORM,
        entity_id=platform_id,
        as_of=snapshot.as_of,
        source_record_id=snapshot.snapshot_id,
        status=snapshot.status,
        headline=f"Institutional data plane: {snapshot.status.value}",
        metrics={
            "healthy_provider_count": snapshot.healthy_provider_count,
            "degraded_provider_count": snapshot.degraded_provider_count,
            "stale_provider_count": snapshot.stale_provider_count,
            "unavailable_provider_count": snapshot.unavailable_provider_count,
            "blocked_domains": [item.value for item in snapshot.blocked_domains],
            "warning_domains": [item.value for item in snapshot.warning_domains],
            "domain_count": len(snapshot.domains),
        },
        blockers=blockers,
        warnings=warnings,
        lineage_ids=tuple(item.readiness_id for item in snapshot.domains),
    )


def project_provider_reliability(
    report: ProviderReliabilityReport,
) -> tuple[CommandCenterComponent, ...]:
    """Project a Stage 9F domain report plus each provider scorecard."""
    report_component = CommandCenterComponent(
        kind=CommandCenterComponentKind.PROVIDER_RELIABILITY,
        entity_kind=CommandCenterEntityKind.PLATFORM,
        entity_id=f"{report.domain.value}:RELIABILITY",
        as_of=report.as_of,
        source_record_id=report.report_id,
        status=report.status,
        headline=f"{report.domain.value} provider reliability: {report.status.value}",
        metrics={
            "domain": report.domain.value,
            "window_start": report.window_start.isoformat(),
            "provider_count": len(report.provider_assessments),
            "incident_count": len(report.incidents),
            "policy_id": report.policy_id,
        },
        blockers=report.blockers,
        warnings=report.warnings,
        lineage_ids=tuple(
            [item.assessment_id for item in report.provider_assessments]
            + [item.incident_id for item in report.incidents]
        ),
    )
    provider_components = tuple(
        CommandCenterComponent(
            kind=CommandCenterComponentKind.PROVIDER_RELIABILITY,
            entity_kind=CommandCenterEntityKind.PROVIDER,
            entity_id=f"{assessment.provider_id}:{report.domain.value}",
            as_of=report.as_of,
            source_record_id=assessment.assessment_id,
            status=assessment.status,
            headline=f"{assessment.provider_id} reliability: {assessment.status.value}",
            metrics={
                "provider_id": assessment.provider_id,
                "domain": report.domain.value,
                "independence_group": assessment.independence_group,
                "role": assessment.role.value,
                "runtime_sample_count": assessment.runtime_sample_count,
                "healthy_runtime_count": assessment.healthy_runtime_count,
                "healthy_ratio": assessment.healthy_ratio,
                "observation_count": assessment.observation_count,
                "eligible_observation_count": assessment.eligible_observation_count,
                "excluded_observation_count": assessment.excluded_observation_count,
                "exclusion_ratio": assessment.exclusion_ratio,
                "incident_count": len(assessment.incident_ids),
            },
            blockers=assessment.blockers,
            warnings=assessment.warnings,
            lineage_ids=assessment.incident_ids,
        )
        for assessment in report.provider_assessments
    )
    return (report_component, *provider_components)


def project_model_governance(
    packet: ModelGovernancePacket,
) -> tuple[CommandCenterComponent, ...]:
    """Project Stage 9G security-level governance and per-model eligibility."""
    packet_component = CommandCenterComponent(
        kind=CommandCenterComponentKind.MODEL_GOVERNANCE,
        entity_kind=CommandCenterEntityKind.SECURITY,
        entity_id=packet.security_id,
        security_id=packet.security_id,
        as_of=packet.as_of,
        source_record_id=packet.packet_id,
        status=packet.status,
        headline=f"Model governance for {packet.security_id}: {packet.status.value}",
        metrics={
            "registered_assessment_count": len(packet.assessments),
            "eligible_model_count": len(packet.eligible_model_view_ids),
            "registry_id": packet.registry_id,
            "policy_id": packet.policy_id,
        },
        blockers=packet.blockers,
        warnings=packet.warnings,
        lineage_ids=tuple(item.assessment_id for item in packet.assessments),
    )
    model_components = tuple(
        CommandCenterComponent(
            kind=CommandCenterComponentKind.MODEL_GOVERNANCE,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id=f"{assessment.model_id}:{assessment.model_version}",
            security_id=packet.security_id,
            as_of=packet.as_of,
            source_record_id=assessment.assessment_id,
            status=assessment.status,
            headline=(
                f"{assessment.model_id} {assessment.model_version} governance: "
                f"{assessment.status.value}"
            ),
            metrics={
                "model_view_id": assessment.model_view_id,
                "lifecycle_stage": assessment.lifecycle_stage.value,
                "validation_id": assessment.validation_id,
                "eligible_for_cio_research": assessment.eligible_for_cio_research,
            },
            blockers=assessment.blockers,
            warnings=assessment.warnings,
            lineage_ids=tuple(
                item
                for item in (
                    assessment.model_view_id,
                    assessment.definition_id,
                    assessment.validation_id,
                )
                if item is not None
            ),
        )
        for assessment in packet.assessments
    )
    return (packet_component, *model_components)


def project_model_stress(
    packet: ModelStressPacket,
) -> tuple[CommandCenterComponent, ...]:
    """Project Stage 9H security-level stress readiness and per-model robustness."""
    packet_component = CommandCenterComponent(
        kind=CommandCenterComponentKind.MODEL_STRESS,
        entity_kind=CommandCenterEntityKind.SECURITY,
        entity_id=packet.security_id,
        security_id=packet.security_id,
        as_of=packet.as_of,
        source_record_id=packet.packet_id,
        status=packet.status,
        headline=f"Model stress for {packet.security_id}: {packet.status.value}",
        metrics={
            "assessment_count": len(packet.assessments),
            "stress_qualified_model_count": len(packet.stress_qualified_model_view_ids),
            "scenario_registry_id": packet.scenario_registry_id,
            "policy_id": packet.policy_id,
        },
        blockers=packet.blockers,
        warnings=packet.warnings,
        lineage_ids=(
            packet.upstream_governance_packet_id,
            *(item.assessment_id for item in packet.assessments),
        ),
    )
    model_components = tuple(
        CommandCenterComponent(
            kind=CommandCenterComponentKind.MODEL_STRESS,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id=f"{assessment.model_id}:{assessment.model_version}",
            security_id=packet.security_id,
            as_of=packet.as_of,
            source_record_id=assessment.assessment_id,
            status=assessment.status,
            headline=(
                f"{assessment.model_id} {assessment.model_version} stress: "
                f"{assessment.status.value}"
            ),
            metrics={
                "model_view_id": assessment.model_view_id,
                "pass_ratio": assessment.pass_ratio,
                "scenario_count": len(assessment.scenario_assessments),
                "covered_classes": [item.value for item in assessment.covered_classes],
                "stress_qualified_for_cio_research": (
                    assessment.stress_qualified_for_cio_research
                ),
            },
            blockers=assessment.blockers,
            warnings=assessment.warnings,
            lineage_ids=(
                assessment.model_view_id,
                assessment.upstream_governance_assessment_id,
                *(item.assessment_id for item in assessment.scenario_assessments),
            ),
        )
        for assessment in packet.assessments
    )
    return (packet_component, *model_components)


def project_model_performance(
    packet: ModelPerformancePacket,
) -> tuple[CommandCenterComponent, ...]:
    """Project Stage 9I realized model performance and alpha-decay surveillance."""
    packet_component = CommandCenterComponent(
        kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
        entity_kind=CommandCenterEntityKind.SECURITY,
        entity_id=packet.security_id,
        security_id=packet.security_id,
        as_of=packet.as_of,
        source_record_id=packet.packet_id,
        status=packet.status,
        headline=f"Model performance for {packet.security_id}: {packet.status.value}",
        metrics={
            "assessment_count": len(packet.assessments),
            "performance_eligible_model_count": len(
                packet.performance_eligible_model_view_ids
            ),
            "policy_id": packet.policy_id,
        },
        blockers=packet.blockers,
        warnings=packet.warnings,
        lineage_ids=(
            packet.upstream_governance_packet_id,
            packet.upstream_stress_packet_id,
            *(item.assessment_id for item in packet.assessments),
        ),
    )
    model_components = tuple(
        CommandCenterComponent(
            kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id=f"{assessment.model_id}:{assessment.model_version}",
            security_id=packet.security_id,
            as_of=packet.as_of,
            source_record_id=assessment.assessment_id,
            status=assessment.status,
            headline=(
                f"{assessment.model_id} {assessment.model_version} performance: "
                f"{assessment.status.value}"
            ),
            metrics={
                "model_view_id": assessment.model_view_id,
                "sample_size": assessment.metrics.sample_size,
                "wins": assessment.metrics.wins,
                "losses": assessment.metrics.losses,
                "breakeven": assessment.metrics.breakeven,
                "hit_rate": assessment.metrics.hit_rate,
                "expectancy_r": assessment.metrics.expectancy_r,
                "profit_factor": assessment.metrics.profit_factor,
                "cumulative_r": assessment.metrics.cumulative_r,
                "max_drawdown_r": assessment.metrics.max_drawdown_r,
                "max_loss_streak": assessment.metrics.max_loss_streak,
                "baseline_expectancy_r": assessment.metrics.baseline_expectancy_r,
                "expectancy_decay_fraction": (
                    assessment.metrics.expectancy_decay_fraction
                ),
                "performance_eligible_for_cio_research": (
                    assessment.performance_eligible_for_cio_research
                ),
            },
            blockers=assessment.blockers,
            warnings=assessment.warnings,
            lineage_ids=(
                assessment.model_view_id,
                assessment.upstream_governance_assessment_id,
                assessment.upstream_stress_assessment_id,
                assessment.baseline_validation_id,
                assessment.metrics.metrics_id,
                *assessment.metrics.outcome_ids,
            ),
        )
        for assessment in packet.assessments
    )
    return (packet_component, *model_components)
