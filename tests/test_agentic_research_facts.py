from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.contracts import EvidenceStatus, ReadinessStatus
from daily_alpha.agentic.data_providers import (
    DataDomain,
    DataRequest,
    ProviderCapability,
    ProviderDefinition,
    ProviderObservation,
    ProviderRegistry,
    ProviderRole,
    SubjectType,
)
from daily_alpha.agentic.event_reconciliation import SourceAuthority
from daily_alpha.agentic.research_facts import (
    ResearchFactError,
    ResearchFactPolicy,
    ResearchFactQuality,
    ResearchFactReconciler,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
PUBLISHED = NOW - timedelta(hours=2)
FUTURE_FISCAL_PERIOD = NOW + timedelta(days=120)


def _definition(provider_id: str, group: str, domain: DataDomain, role: ProviderRole):
    return ProviderDefinition(
        provider_id=provider_id,
        display_name=provider_id,
        independence_group=group,
        source_version="V1",
        capabilities=(
            ProviderCapability(
                domain=domain,
                role=role,
                cadence_seconds=300,
                max_freshness_seconds=86_400,
                supports_point_in_time_history=True,
            ),
        ),
    )


def _request(
    domain: DataDomain,
    metric: str,
    *,
    subject_type: SubjectType = SubjectType.SECURITY,
) -> DataRequest:
    if subject_type is SubjectType.SECURITY:
        return DataRequest(
            domain=domain,
            metric=metric,
            as_of=NOW,
            subject_type=subject_type,
            security_id="DAI-SEC-0001",
        )
    return DataRequest(
        domain=domain,
        metric=metric,
        as_of=NOW,
        subject_type=subject_type,
        global_series_id="US_CPI",
    )


def _observation(
    provider_id: str,
    group: str,
    domain: DataDomain,
    metric: str,
    authority: SourceAuthority,
    *,
    fact_key: str = "FACT-1",
    fact_value=100.0,
    published_at: datetime = PUBLISHED,
    period_end: datetime | None = None,
    unit: str | None = None,
    revision_id: str | None = None,
    document_id: str | None = None,
    subject_key: str = "SECURITY:DAI-SEC-0001",
    status: EvidenceStatus = EvidenceStatus.COMPLETE,
) -> ProviderObservation:
    return ProviderObservation(
        provider_id=provider_id,
        independence_group=group,
        domain=domain,
        metric=metric,
        subject_key=subject_key,
        value={
            "authority": authority.value,
            "fact_key": fact_key,
            "fact_value": fact_value,
            "published_at": published_at.isoformat(),
            "period_end": period_end.isoformat() if period_end else None,
            "unit": unit,
            "revision_id": revision_id,
            "primary_document_id": document_id,
        },
        observed_at=published_at,
        received_at=published_at + timedelta(seconds=2),
        source_version="V1",
        status=status,
        confidence=1.0 if status is EvidenceStatus.COMPLETE else 0.0,
    )


def test_primary_fundamental_fact_is_verified_and_passes():
    registry = ProviderRegistry(
        (
            _definition(
                "SEC_XBRL",
                "SEC_PRIMARY",
                DataDomain.FUNDAMENTALS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.FUNDAMENTALS, "REVENUE_TTM"),
        (
            _observation(
                "SEC_XBRL",
                "SEC_PRIMARY",
                DataDomain.FUNDAMENTALS,
                "REVENUE_TTM",
                SourceAuthority.REGULATOR_PRIMARY,
                fact_value=12_500_000_000,
                unit="USD",
                document_id="10-Q-2026Q2",
            ),
        ),
    )
    assert state.status is ReadinessStatus.PASS
    assert state.quality is ResearchFactQuality.VERIFIED_PRIMARY
    assert state.canonical_candidate["fact_value"] == 12_500_000_000


def test_single_normalized_fundamental_is_warning_grade_not_unquestioned_truth():
    registry = ProviderRegistry(
        (
            _definition(
                "FUND_VENDOR",
                "VENDOR_A",
                DataDomain.FUNDAMENTALS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.FUNDAMENTALS, "GROSS_MARGIN"),
        (
            _observation(
                "FUND_VENDOR",
                "VENDOR_A",
                DataDomain.FUNDAMENTALS,
                "GROSS_MARGIN",
                SourceAuthority.VENDOR_NORMALIZED,
                fact_value=0.42,
                unit="RATIO",
            ),
        ),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.quality is ResearchFactQuality.SINGLE_SOURCE
    assert "RESEARCH_SINGLE_SOURCE:FUNDAMENTALS" in state.warnings


def test_two_independent_matching_normalized_facts_are_corroborated():
    registry = ProviderRegistry(
        (
            _definition("VENDOR_A", "UPSTREAM_A", DataDomain.FUNDAMENTALS, ProviderRole.PRIMARY),
            _definition("VENDOR_B", "UPSTREAM_B", DataDomain.FUNDAMENTALS, ProviderRole.SECONDARY),
        )
    )
    first = _observation(
        "VENDOR_A",
        "UPSTREAM_A",
        DataDomain.FUNDAMENTALS,
        "EPS_TTM",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=5.25,
        unit="USD_PER_SHARE",
    )
    second = _observation(
        "VENDOR_B",
        "UPSTREAM_B",
        DataDomain.FUNDAMENTALS,
        "EPS_TTM",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=5.25,
        unit="USD_PER_SHARE",
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.FUNDAMENTALS, "EPS_TTM"),
        (first, second),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.quality is ResearchFactQuality.CORROBORATED
    assert "RESEARCH_NO_PRIMARY_SOURCE:FUNDAMENTALS" in state.warnings


def test_independent_nonprimary_fact_conflict_blocks():
    registry = ProviderRegistry(
        (
            _definition("VENDOR_A", "UPSTREAM_A", DataDomain.FUNDAMENTALS, ProviderRole.PRIMARY),
            _definition("VENDOR_B", "UPSTREAM_B", DataDomain.FUNDAMENTALS, ProviderRole.SECONDARY),
        )
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.FUNDAMENTALS, "EPS_TTM"),
        (
            _observation(
                "VENDOR_A",
                "UPSTREAM_A",
                DataDomain.FUNDAMENTALS,
                "EPS_TTM",
                SourceAuthority.VENDOR_NORMALIZED,
                fact_value=5.25,
            ),
            _observation(
                "VENDOR_B",
                "UPSTREAM_B",
                DataDomain.FUNDAMENTALS,
                "EPS_TTM",
                SourceAuthority.VENDOR_NORMALIZED,
                fact_value=5.55,
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert state.quality is ResearchFactQuality.BLOCKED
    assert "RESEARCH_NONPRIMARY_CONFLICT" in state.blockers


def test_official_macro_release_requires_primary_authority():
    registry = ProviderRegistry(
        (
            _definition("MACRO_VENDOR", "UPSTREAM_A", DataDomain.MACRO, ProviderRole.PRIMARY),
            _definition("MACRO_VENDOR_2", "UPSTREAM_B", DataDomain.MACRO, ProviderRole.SECONDARY),
        )
    )
    request = _request(DataDomain.MACRO, "CPI_YOY", subject_type=SubjectType.GLOBAL)
    first = _observation(
        "MACRO_VENDOR",
        "UPSTREAM_A",
        DataDomain.MACRO,
        "CPI_YOY",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=0.027,
        subject_key="GLOBAL:US_CPI",
    )
    second = _observation(
        "MACRO_VENDOR_2",
        "UPSTREAM_B",
        DataDomain.MACRO,
        "CPI_YOY",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=0.027,
        subject_key="GLOBAL:US_CPI",
    )
    state = ResearchFactReconciler(registry).reconcile(request, (first, second))
    assert state.status is ReadinessStatus.BLOCKED
    assert "RESEARCH_PRIMARY_SOURCE_REQUIRED:MACRO" in state.blockers


def test_official_macro_primary_passes():
    registry = ProviderRegistry(
        (
            _definition("BLS", "BLS_PRIMARY", DataDomain.MACRO, ProviderRole.PRIMARY),
        )
    )
    request = _request(DataDomain.MACRO, "CPI_YOY", subject_type=SubjectType.GLOBAL)
    state = ResearchFactReconciler(registry).reconcile(
        request,
        (
            _observation(
                "BLS",
                "BLS_PRIMARY",
                DataDomain.MACRO,
                "CPI_YOY",
                SourceAuthority.REGULATOR_PRIMARY,
                fact_value=0.027,
                unit="RATIO",
                document_id="BLS-CPI-2026-07",
                subject_key="GLOBAL:US_CPI",
            ),
        ),
    )
    assert state.status is ReadinessStatus.PASS
    assert state.quality is ResearchFactQuality.VERIFIED_PRIMARY


def test_future_estimate_period_is_allowed_when_estimate_was_known_as_of_boundary():
    registry = ProviderRegistry(
        (
            _definition(
                "EST_VENDOR",
                "EST_UPSTREAM",
                DataDomain.ESTIMATES_REVISIONS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.ESTIMATES_REVISIONS, "EPS_CONSENSUS"),
        (
            _observation(
                "EST_VENDOR",
                "EST_UPSTREAM",
                DataDomain.ESTIMATES_REVISIONS,
                "EPS_CONSENSUS",
                SourceAuthority.VENDOR_NORMALIZED,
                fact_value=6.10,
                period_end=FUTURE_FISCAL_PERIOD,
                unit="USD_PER_SHARE",
                revision_id="REV-20260821",
            ),
        ),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.canonical_candidate["period_end"] == FUTURE_FISCAL_PERIOD.isoformat()


def test_primary_news_catalyst_outweighs_conflicting_secondary_summary():
    registry = ProviderRegistry(
        (
            _definition("ISSUER_IR", "ISSUER", DataDomain.NEWS_CATALYSTS, ProviderRole.PRIMARY),
            _definition("NEWS_VENDOR", "NEWS_UPSTREAM", DataDomain.NEWS_CATALYSTS, ProviderRole.SECONDARY),
        )
    )
    primary = _observation(
        "ISSUER_IR",
        "ISSUER",
        DataDomain.NEWS_CATALYSTS,
        "GUIDANCE_CHANGE",
        SourceAuthority.ISSUER_PRIMARY,
        fact_value={"direction": "RAISED"},
        document_id="IR-GUIDANCE-20260821",
    )
    secondary = _observation(
        "NEWS_VENDOR",
        "NEWS_UPSTREAM",
        DataDomain.NEWS_CATALYSTS,
        "GUIDANCE_CHANGE",
        SourceAuthority.SECONDARY,
        fact_value={"direction": "UNCHANGED"},
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.NEWS_CATALYSTS, "GUIDANCE_CHANGE"),
        (secondary, primary),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.quality is ResearchFactQuality.VERIFIED_PRIMARY
    assert state.canonical_candidate["provider_id"] == "ISSUER_IR"
    assert "RESEARCH_SECONDARY_CONFLICT_WITH_PRIMARY:NEWS_VENDOR" in state.warnings


def test_behavioral_single_source_is_explicitly_single_source_warning():
    registry = ProviderRegistry(
        (
            _definition("ALT_DATA", "ALT_UPSTREAM", DataDomain.BEHAVIORAL, ProviderRole.OPTIONAL),
        )
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.BEHAVIORAL, "SEARCH_ATTENTION"),
        (
            _observation(
                "ALT_DATA",
                "ALT_UPSTREAM",
                DataDomain.BEHAVIORAL,
                "SEARCH_ATTENTION",
                SourceAuthority.SECONDARY,
                fact_value={"z_score": 2.1},
            ),
        ),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.quality is ResearchFactQuality.SINGLE_SOURCE


def test_numeric_tolerance_can_reconcile_small_provider_rounding_differences():
    registry = ProviderRegistry(
        (
            _definition("VENDOR_A", "UPSTREAM_A", DataDomain.ESTIMATES_REVISIONS, ProviderRole.PRIMARY),
            _definition("VENDOR_B", "UPSTREAM_B", DataDomain.ESTIMATES_REVISIONS, ProviderRole.SECONDARY),
        )
    )
    request = _request(DataDomain.ESTIMATES_REVISIONS, "EPS_CONSENSUS")
    first = _observation(
        "VENDOR_A",
        "UPSTREAM_A",
        DataDomain.ESTIMATES_REVISIONS,
        "EPS_CONSENSUS",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=6.100,
    )
    second = _observation(
        "VENDOR_B",
        "UPSTREAM_B",
        DataDomain.ESTIMATES_REVISIONS,
        "EPS_CONSENSUS",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=6.104,
    )
    state = ResearchFactReconciler(registry).reconcile(
        request,
        (first, second),
        policy=ResearchFactPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(),
            min_independent_groups=2,
            numeric_tolerance_abs=0.01,
        ),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.quality is ResearchFactQuality.CORROBORATED


def test_noncomplete_research_source_is_visible_and_not_promoted():
    registry = ProviderRegistry(
        (
            _definition("ALT_DATA", "ALT_UPSTREAM", DataDomain.BEHAVIORAL, ProviderRole.OPTIONAL),
        )
    )
    state = ResearchFactReconciler(registry).reconcile(
        _request(DataDomain.BEHAVIORAL, "WEB_TRAFFIC"),
        (
            _observation(
                "ALT_DATA",
                "ALT_UPSTREAM",
                DataDomain.BEHAVIORAL,
                "WEB_TRAFFIC",
                SourceAuthority.SECONDARY,
                fact_value={"growth": 0.15},
                status=EvidenceStatus.SOURCE_UNAVAILABLE,
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "RESEARCH_SOURCE_EXCLUDED:ALT_DATA:SOURCE_UNAVAILABLE" in state.warnings


def test_research_state_identity_is_input_order_independent():
    registry = ProviderRegistry(
        (
            _definition("VENDOR_A", "UPSTREAM_A", DataDomain.FUNDAMENTALS, ProviderRole.PRIMARY),
            _definition("VENDOR_B", "UPSTREAM_B", DataDomain.FUNDAMENTALS, ProviderRole.SECONDARY),
        )
    )
    first = _observation(
        "VENDOR_A",
        "UPSTREAM_A",
        DataDomain.FUNDAMENTALS,
        "EPS_TTM",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=5.25,
    )
    second = _observation(
        "VENDOR_B",
        "UPSTREAM_B",
        DataDomain.FUNDAMENTALS,
        "EPS_TTM",
        SourceAuthority.VENDOR_NORMALIZED,
        fact_value=5.25,
    )
    reconciler = ResearchFactReconciler(registry)
    left = reconciler.reconcile(_request(DataDomain.FUNDAMENTALS, "EPS_TTM"), (first, second))
    right = reconciler.reconcile(_request(DataDomain.FUNDAMENTALS, "EPS_TTM"), (second, first))
    assert left.state_id == right.state_id


def test_unsupported_domain_is_rejected():
    with pytest.raises(ResearchFactError, match="RESEARCH_RECONCILIATION_DOMAIN_UNSUPPORTED"):
        ResearchFactReconciler(ProviderRegistry()).reconcile(
            _request(DataDomain.MARKET_BARS, "OHLCV_1M"),
            (),
        )
