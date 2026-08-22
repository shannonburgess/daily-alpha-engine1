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
from daily_alpha.agentic.event_reconciliation import (
    EventDataError,
    EventReconciler,
    SourceAuthority,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
PUBLISHED = NOW - timedelta(hours=1)
FUTURE_EVENT = NOW + timedelta(days=10)


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


def _request(domain: DataDomain, metric: str = "MATERIAL_EVENT") -> DataRequest:
    return DataRequest(
        domain=domain,
        metric=metric,
        as_of=NOW,
        subject_type=SubjectType.SECURITY,
        security_id="DAI-SEC-0001",
    )


def _observation(
    provider_id: str,
    group: str,
    domain: DataDomain,
    authority: SourceAuthority,
    *,
    event_key: str = "EVENT-1",
    event_type: str = "EARNINGS_DATE",
    event_time: datetime = FUTURE_EVENT,
    published_at: datetime = PUBLISHED,
    facts: dict | None = None,
    document_id: str | None = None,
    status: EvidenceStatus = EvidenceStatus.COMPLETE,
) -> ProviderObservation:
    facts = facts or {"session": "AFTER_CLOSE"}
    return ProviderObservation(
        provider_id=provider_id,
        independence_group=group,
        domain=domain,
        metric="MATERIAL_EVENT",
        subject_key="SECURITY:DAI-SEC-0001",
        value={
            "event_key": event_key,
            "event_type": event_type,
            "event_time": event_time.isoformat(),
            "published_at": published_at.isoformat(),
            "authority": authority.value,
            "facts": facts,
            "primary_document_id": document_id,
        },
        observed_at=published_at,
        received_at=published_at + timedelta(seconds=2),
        source_version="V1",
        status=status,
        confidence=1.0 if status is EvidenceStatus.COMPLETE else 0.0,
    )


def test_future_scheduled_earnings_event_is_valid_when_information_is_already_known():
    registry = ProviderRegistry(
        (
            _definition(
                "ISSUER_IR",
                "ISSUER",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    observation = _observation(
        "ISSUER_IR",
        "ISSUER",
        DataDomain.EARNINGS_EVENTS,
        SourceAuthority.ISSUER_PRIMARY,
        document_id="IR-CALENDAR-2026Q3",
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.EARNINGS_EVENTS),
        (observation,),
    )
    assert state.status is ReadinessStatus.PASS
    assert state.canonical_authority is SourceAuthority.ISSUER_PRIMARY
    assert state.canonical_candidate["event_time"] == FUTURE_EVENT.isoformat()


def test_issuer_primary_outweighs_conflicting_vendor_copy_but_conflict_is_visible():
    registry = ProviderRegistry(
        (
            _definition(
                "ISSUER_IR",
                "ISSUER",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "VENDOR_A",
                "VENDOR_A_UPSTREAM",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    primary = _observation(
        "ISSUER_IR",
        "ISSUER",
        DataDomain.EARNINGS_EVENTS,
        SourceAuthority.ISSUER_PRIMARY,
        document_id="IR-CALENDAR-2026Q3",
        facts={"session": "AFTER_CLOSE"},
    )
    vendor = _observation(
        "VENDOR_A",
        "VENDOR_A_UPSTREAM",
        DataDomain.EARNINGS_EVENTS,
        SourceAuthority.VENDOR_NORMALIZED,
        facts={"session": "BEFORE_OPEN"},
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.EARNINGS_EVENTS),
        (vendor, primary),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.canonical_candidate["provider_id"] == "ISSUER_IR"
    assert "SECONDARY_EVENT_CONFLICT_WITH_PRIMARY:VENDOR_A" in state.warnings


def test_vendor_only_earnings_requires_two_independent_groups():
    registry = ProviderRegistry(
        (
            _definition(
                "VENDOR_A",
                "SAME_UPSTREAM",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "VENDOR_B",
                "SAME_UPSTREAM",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.EARNINGS_EVENTS),
        (
            _observation(
                "VENDOR_A",
                "SAME_UPSTREAM",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.VENDOR_NORMALIZED,
            ),
            _observation(
                "VENDOR_B",
                "SAME_UPSTREAM",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.VENDOR_NORMALIZED,
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "INSUFFICIENT_VENDOR_CORROBORATION:1<2" in state.blockers


def test_two_independent_matching_vendors_can_supply_warning_grade_earnings_fact():
    registry = ProviderRegistry(
        (
            _definition(
                "VENDOR_A",
                "UPSTREAM_A",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "VENDOR_B",
                "UPSTREAM_B",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.EARNINGS_EVENTS),
        (
            _observation(
                "VENDOR_A",
                "UPSTREAM_A",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.VENDOR_NORMALIZED,
            ),
            _observation(
                "VENDOR_B",
                "UPSTREAM_B",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.VENDOR_NORMALIZED,
            ),
        ),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.canonical_candidate is not None
    assert "NO_PRIMARY_SOURCE:EARNINGS_EVENTS" in state.warnings


def test_conflicting_vendor_earnings_facts_block():
    registry = ProviderRegistry(
        (
            _definition(
                "VENDOR_A",
                "UPSTREAM_A",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "VENDOR_B",
                "UPSTREAM_B",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.EARNINGS_EVENTS),
        (
            _observation(
                "VENDOR_A",
                "UPSTREAM_A",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.VENDOR_NORMALIZED,
                facts={"session": "AFTER_CLOSE"},
            ),
            _observation(
                "VENDOR_B",
                "UPSTREAM_B",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.VENDOR_NORMALIZED,
                facts={"session": "BEFORE_OPEN"},
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "VENDOR_EVENT_CONFLICT" in state.blockers


def test_sec_filing_requires_regulatory_primary_source():
    registry = ProviderRegistry(
        (
            _definition(
                "FILING_VENDOR",
                "VENDOR_UPSTREAM",
                DataDomain.SEC_FILINGS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "FILING_VENDOR_2",
                "VENDOR_UPSTREAM_2",
                DataDomain.SEC_FILINGS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.SEC_FILINGS),
        (
            _observation(
                "FILING_VENDOR",
                "VENDOR_UPSTREAM",
                DataDomain.SEC_FILINGS,
                SourceAuthority.VENDOR_NORMALIZED,
                event_type="8-K",
            ),
            _observation(
                "FILING_VENDOR_2",
                "VENDOR_UPSTREAM_2",
                DataDomain.SEC_FILINGS,
                SourceAuthority.VENDOR_NORMALIZED,
                event_type="8-K",
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "PRIMARY_SOURCE_REQUIRED:SEC_FILINGS" in state.blockers


def test_sec_regulator_primary_passes_without_vendor_dependency():
    registry = ProviderRegistry(
        (
            _definition(
                "SEC_EDGAR",
                "SEC_PRIMARY",
                DataDomain.SEC_FILINGS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.SEC_FILINGS),
        (
            _observation(
                "SEC_EDGAR",
                "SEC_PRIMARY",
                DataDomain.SEC_FILINGS,
                SourceAuthority.REGULATOR_PRIMARY,
                event_type="8-K",
                document_id="0000000000-26-000001",
                facts={"form": "8-K", "items": ["2.02"]},
            ),
        ),
    )
    assert state.status is ReadinessStatus.PASS
    assert state.canonical_candidate["provider_id"] == "SEC_EDGAR"


def test_primary_sources_disagreeing_on_same_event_block():
    registry = ProviderRegistry(
        (
            _definition(
                "ISSUER_IR",
                "ISSUER",
                DataDomain.CORPORATE_ACTIONS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "EXCHANGE",
                "EXCHANGE",
                DataDomain.CORPORATE_ACTIONS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    issuer = _observation(
        "ISSUER_IR",
        "ISSUER",
        DataDomain.CORPORATE_ACTIONS,
        SourceAuthority.ISSUER_PRIMARY,
        event_type="SPLIT",
        document_id="ISSUER-SPLIT-NOTICE",
        facts={"ratio": "2:1"},
    )
    exchange = _observation(
        "EXCHANGE",
        "EXCHANGE",
        DataDomain.CORPORATE_ACTIONS,
        SourceAuthority.EXCHANGE_PRIMARY,
        event_type="SPLIT",
        document_id="EXCHANGE-SPLIT-NOTICE",
        facts={"ratio": "3:1"},
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.CORPORATE_ACTIONS),
        (exchange, issuer),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert any(item.startswith("PRIMARY_EVENT_CONFLICT:") for item in state.blockers)


def test_primary_event_requires_document_identity():
    registry = ProviderRegistry(
        (
            _definition(
                "ISSUER_IR",
                "ISSUER",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.EARNINGS_EVENTS),
        (
            _observation(
                "ISSUER_IR",
                "ISSUER",
                DataDomain.EARNINGS_EVENTS,
                SourceAuthority.ISSUER_PRIMARY,
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert any("PRIMARY_EVENT_DOCUMENT_ID_REQUIRED" in item for item in state.blockers)


def test_event_state_is_deterministic_regardless_of_input_order():
    registry = ProviderRegistry(
        (
            _definition(
                "VENDOR_A",
                "UPSTREAM_A",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.PRIMARY,
            ),
            _definition(
                "VENDOR_B",
                "UPSTREAM_B",
                DataDomain.EARNINGS_EVENTS,
                ProviderRole.SECONDARY,
            ),
        )
    )
    first = _observation(
        "VENDOR_A",
        "UPSTREAM_A",
        DataDomain.EARNINGS_EVENTS,
        SourceAuthority.VENDOR_NORMALIZED,
    )
    second = _observation(
        "VENDOR_B",
        "UPSTREAM_B",
        DataDomain.EARNINGS_EVENTS,
        SourceAuthority.VENDOR_NORMALIZED,
    )
    reconciler = EventReconciler(registry)
    left = reconciler.reconcile(_request(DataDomain.EARNINGS_EVENTS), (first, second))
    right = reconciler.reconcile(_request(DataDomain.EARNINGS_EVENTS), (second, first))
    assert left.state_id == right.state_id


def test_noncomplete_event_source_is_visible_but_not_promoted():
    registry = ProviderRegistry(
        (
            _definition(
                "SEC_EDGAR",
                "SEC_PRIMARY",
                DataDomain.SEC_FILINGS,
                ProviderRole.PRIMARY,
            ),
        )
    )
    state = EventReconciler(registry).reconcile(
        _request(DataDomain.SEC_FILINGS),
        (
            _observation(
                "SEC_EDGAR",
                "SEC_PRIMARY",
                DataDomain.SEC_FILINGS,
                SourceAuthority.REGULATOR_PRIMARY,
                event_type="8-K",
                document_id="0000000000-26-000001",
                status=EvidenceStatus.SOURCE_UNAVAILABLE,
            ),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "EVENT_SOURCE_EXCLUDED:SEC_EDGAR:SOURCE_UNAVAILABLE" in state.warnings
    assert "PRIMARY_SOURCE_REQUIRED:SEC_FILINGS" in state.blockers


def test_unsupported_domain_is_rejected():
    registry = ProviderRegistry()
    with pytest.raises(EventDataError, match="EVENT_RECONCILIATION_DOMAIN_UNSUPPORTED"):
        EventReconciler(registry).reconcile(_request(DataDomain.FUNDAMENTALS), ())
