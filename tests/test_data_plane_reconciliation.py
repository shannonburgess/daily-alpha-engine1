from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.aws_transport import SourceTransportTelemetry
from daily_alpha.agentic.contracts import EvidenceStatus, ReadinessStatus
from daily_alpha.agentic.data_plane_readiness import (
    DomainReadinessPolicy,
    InstitutionalDataPlaneReadinessEngine,
)
from daily_alpha.agentic.data_plane_reconciliation import (
    CanonicalRoute,
    DataPlaneReconciliationError,
    InstitutionalReconciliationGateway,
)
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
from daily_alpha.agentic.durable_evidence import SourceHealthStatus
from daily_alpha.agentic.research_facts import ResearchFactQuality
from daily_alpha.agentic.vendor_adapters import (
    DatabentoHistoricalAdapter,
    FinancialModelingPrepAdapter,
    MassiveStocksAdapter,
)


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
BAR_END = AS_OF - timedelta(seconds=20)
BAR_START = BAR_END - timedelta(minutes=1)


def _third_market_definition() -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="MARKET_THIRD",
        display_name="Third Fixture Market Source",
        independence_group="MARKET_THIRD_SOURCE",
        source_version="THIRD_FIXTURE_V1",
        capabilities=(
            ProviderCapability(
                domain=DataDomain.MARKET_BARS,
                role=ProviderRole.OPTIONAL,
                cadence_seconds=60,
                max_freshness_seconds=120,
                supports_point_in_time_history=True,
            ),
        ),
    )


def _market_registry(*, include_third: bool = False) -> ProviderRegistry:
    definitions = [MassiveStocksAdapter.definition(), DatabentoHistoricalAdapter.definition()]
    if include_third:
        definitions.append(_third_market_definition())
    return ProviderRegistry(tuple(definitions))


def _fundamental_registry() -> ProviderRegistry:
    return ProviderRegistry((FinancialModelingPrepAdapter.definition(),))


def _market_request() -> DataRequest:
    return DataRequest(
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV",
        as_of=AS_OF,
        subject_type=SubjectType.SECURITY,
        security_id="SEC-AAPL",
    )


def _market_observation(
    *,
    provider_id: str,
    independence_group: str,
    open_price: float = 100.0,
    close: float = 100.2,
    volume: float = 1_000.0,
) -> ProviderObservation:
    return ProviderObservation(
        provider_id=provider_id,
        independence_group=independence_group,
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV",
        subject_key="SECURITY:SEC-AAPL",
        value={
            "timeframe": "1M",
            "bar_start": BAR_START.isoformat(),
            "bar_end": BAR_END.isoformat(),
            "open": open_price,
            "high": 100.5,
            "low": 99.8,
            "close": close,
            "volume": volume,
        },
        observed_at=BAR_END,
        received_at=BAR_END + timedelta(seconds=2),
        source_version="FIXTURE_V1",
        status=EvidenceStatus.COMPLETE,
        confidence=1.0,
    )


def _healthy(provider_id: str) -> SourceTransportTelemetry:
    return SourceTransportTelemetry(
        provider_id=provider_id,
        observed_at=AS_OF - timedelta(seconds=5),
        status=SourceHealthStatus.HEALTHY,
        latency_ms=25.0,
        freshness_seconds=5.0,
        last_success_at=AS_OF - timedelta(seconds=5),
    )


def _degraded(provider_id: str) -> SourceTransportTelemetry:
    return SourceTransportTelemetry(
        provider_id=provider_id,
        observed_at=AS_OF - timedelta(seconds=5),
        status=SourceHealthStatus.DEGRADED,
        latency_ms=250.0,
        freshness_seconds=5.0,
        last_success_at=AS_OF - timedelta(seconds=30),
        reason_code="FIXTURE_DEGRADED",
    )


def _unavailable(provider_id: str) -> SourceTransportTelemetry:
    return SourceTransportTelemetry(
        provider_id=provider_id,
        observed_at=AS_OF - timedelta(seconds=5),
        status=SourceHealthStatus.UNAVAILABLE,
        latency_ms=None,
        freshness_seconds=30.0,
        last_success_at=AS_OF - timedelta(minutes=5),
        reason_code="FIXTURE_UNAVAILABLE",
    )


def _market_snapshot(
    *,
    registry: ProviderRegistry,
    telemetry: tuple[SourceTransportTelemetry, ...],
    min_groups: int = 2,
):
    return InstitutionalDataPlaneReadinessEngine(registry=registry).evaluate(
        policies=(
            DomainReadinessPolicy(
                domain=DataDomain.MARKET_BARS,
                min_independent_groups=min_groups,
                max_latency_ms=100.0,
                max_freshness_seconds=120,
                required=True,
            ),
        ),
        telemetry=telemetry,
        as_of=AS_OF,
    )


def test_two_healthy_market_sources_reconcile_through_readiness_gate() -> None:
    registry = _market_registry()
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(_healthy("MASSIVE"), _healthy("DATABENTO")),
    )
    observations = (
        _market_observation(
            provider_id="MASSIVE",
            independence_group="MASSIVE_MARKET_DATA",
        ),
        _market_observation(
            provider_id="DATABENTO",
            independence_group="DATABENTO_MARKET_DATA",
            open_price=100.01,
            close=100.21,
            volume=1_040.0,
        ),
    )

    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_market_request(),
        observations=observations,
        readiness_snapshot=snapshot,
    )

    assert snapshot.status is ReadinessStatus.PASS
    assert result.status is ReadinessStatus.PASS
    assert result.route is CanonicalRoute.MARKET_BAR
    assert result.canonical_state is not None
    assert result.canonical_state.status is ReadinessStatus.PASS
    assert result.canonical_state.canonical_provider_id == "MASSIVE"
    assert result.canonical_state.selected_provider_ids == ("DATABENTO", "MASSIVE")
    assert result.eligible_observation_ids == tuple(sorted(item.observation_id for item in observations))
    assert result.excluded_observation_ids == ()
    assert result.data_plane_snapshot_id == snapshot.snapshot_id
    assert result.domain_readiness_id == snapshot.domains[0].readiness_id
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_blocked_domain_readiness_prevents_complete_payload_from_canonicalizing() -> None:
    registry = _market_registry()
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(_healthy("MASSIVE"), _unavailable("DATABENTO")),
    )
    observations = (
        _market_observation(
            provider_id="MASSIVE",
            independence_group="MASSIVE_MARKET_DATA",
        ),
        _market_observation(
            provider_id="DATABENTO",
            independence_group="DATABENTO_MARKET_DATA",
        ),
    )

    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_market_request(),
        observations=observations,
        readiness_snapshot=snapshot,
    )

    assert snapshot.status is ReadinessStatus.BLOCKED
    assert result.status is ReadinessStatus.BLOCKED
    assert result.canonical_state is None
    assert "DOMAIN_OPERATIONAL_READINESS_BLOCKED" in result.blockers
    assert result.eligible_observation_ids == ()
    assert result.excluded_observation_ids == tuple(sorted(item.observation_id for item in observations))


def test_degraded_third_provider_is_excluded_and_warning_propagates() -> None:
    registry = _market_registry(include_third=True)
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(
            _healthy("MASSIVE"),
            _healthy("DATABENTO"),
            _degraded("MARKET_THIRD"),
        ),
    )
    third = _market_observation(
        provider_id="MARKET_THIRD",
        independence_group="MARKET_THIRD_SOURCE",
        open_price=100.0,
        close=100.2,
        volume=1_000.0,
    )
    observations = (
        _market_observation(
            provider_id="MASSIVE",
            independence_group="MASSIVE_MARKET_DATA",
        ),
        _market_observation(
            provider_id="DATABENTO",
            independence_group="DATABENTO_MARKET_DATA",
            open_price=100.01,
            close=100.21,
            volume=1_030.0,
        ),
        third,
    )

    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_market_request(),
        observations=observations,
        readiness_snapshot=snapshot,
    )

    assert snapshot.status is ReadinessStatus.WARNING
    assert result.status is ReadinessStatus.WARNING
    assert result.canonical_state is not None
    assert result.canonical_state.status is ReadinessStatus.PASS
    assert third.observation_id in result.excluded_observation_ids
    third_assessment = next(item for item in result.eligibility if item.provider_id == "MARKET_THIRD")
    assert third_assessment.eligible is False
    assert third_assessment.runtime_status is not None
    assert third_assessment.runtime_status.value == "DEGRADED"
    assert "OBSERVATION_EXCLUDED_DEGRADED:MARKET_THIRD" in result.warnings


def test_unassessed_provider_injection_fails_closed() -> None:
    registry = _market_registry()
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(_healthy("MASSIVE"), _healthy("DATABENTO")),
    )
    rogue = _market_observation(
        provider_id="ROGUE",
        independence_group="ROGUE_SOURCE",
    )
    observations = (
        _market_observation(
            provider_id="MASSIVE",
            independence_group="MASSIVE_MARKET_DATA",
        ),
        _market_observation(
            provider_id="DATABENTO",
            independence_group="DATABENTO_MARKET_DATA",
        ),
        rogue,
    )

    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_market_request(),
        observations=observations,
        readiness_snapshot=snapshot,
    )

    assert result.status is ReadinessStatus.BLOCKED
    assert result.canonical_state is None
    assert "PROVIDER_NOT_ASSESSED_FOR_DOMAIN:ROGUE" in result.blockers
    assert rogue.observation_id in result.excluded_observation_ids


def test_reconciliation_identity_is_input_order_independent() -> None:
    registry = _market_registry()
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(_healthy("MASSIVE"), _healthy("DATABENTO")),
    )
    observations = (
        _market_observation(
            provider_id="MASSIVE",
            independence_group="MASSIVE_MARKET_DATA",
        ),
        _market_observation(
            provider_id="DATABENTO",
            independence_group="DATABENTO_MARKET_DATA",
            open_price=100.01,
            close=100.21,
            volume=1_030.0,
        ),
    )
    gateway = InstitutionalReconciliationGateway(registry=registry)

    first = gateway.reconcile(
        request=_market_request(),
        observations=observations,
        readiness_snapshot=snapshot,
    )
    second = gateway.reconcile(
        request=_market_request(),
        observations=tuple(reversed(observations)),
        readiness_snapshot=snapshot,
    )

    assert first.result_id == second.result_id
    assert first.canonical_state_id == second.canonical_state_id


def test_fmp_fundamental_fact_dispatches_to_research_reconciler() -> None:
    registry = _fundamental_registry()
    snapshot = InstitutionalDataPlaneReadinessEngine(registry=registry).evaluate(
        policies=(
            DomainReadinessPolicy(
                domain=DataDomain.FUNDAMENTALS,
                min_independent_groups=1,
                max_freshness_seconds=172_800,
                required=True,
            ),
        ),
        telemetry=(_healthy("FMP"),),
        as_of=AS_OF,
    )
    request = DataRequest(
        domain=DataDomain.FUNDAMENTALS,
        metric="INCOME_STATEMENT",
        as_of=AS_OF,
        subject_type=SubjectType.SECURITY,
        security_id="SEC-AAPL",
    )
    observation = ProviderObservation(
        provider_id="FMP",
        independence_group="FMP_NORMALIZED",
        domain=DataDomain.FUNDAMENTALS,
        metric="INCOME_STATEMENT",
        subject_key="SECURITY:SEC-AAPL",
        value={
            "authority": "VENDOR_NORMALIZED",
            "fact_key": "INCOME_STATEMENT:2026-06-30:Q3",
            "fact_value": {"revenue": 1000.0, "netIncome": 100.0},
            "published_at": (AS_OF - timedelta(minutes=1)).isoformat(),
            "period_end": datetime(2026, 6, 30, tzinfo=UTC).isoformat(),
            "unit": "USD",
            "revision_id": "fixture-rev-1",
            "primary_document_id": None,
        },
        observed_at=AS_OF - timedelta(minutes=1),
        received_at=AS_OF - timedelta(minutes=1),
        source_version="FMP_STABLE_V1",
        status=EvidenceStatus.COMPLETE,
        confidence=0.90,
    )

    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=request,
        observations=(observation,),
        readiness_snapshot=snapshot,
    )

    assert result.route is CanonicalRoute.RESEARCH_FACT
    assert result.status is ReadinessStatus.WARNING
    assert result.canonical_state is not None
    assert result.canonical_state.quality is ResearchFactQuality.SINGLE_SOURCE
    assert result.canonical_state.selected_provider_ids == ("FMP",)
    assert "RESEARCH_SINGLE_SOURCE:FUNDAMENTALS" in result.warnings


def test_readiness_snapshot_must_match_request_as_of_exactly() -> None:
    registry = _market_registry()
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(_healthy("MASSIVE"), _healthy("DATABENTO")),
    )
    request = replace(_market_request(), as_of=AS_OF + timedelta(seconds=1))

    with pytest.raises(
        DataPlaneReconciliationError,
        match="READINESS_SNAPSHOT_AS_OF_REQUEST_MISMATCH",
    ):
        InstitutionalReconciliationGateway(registry=registry).reconcile(
            request=request,
            observations=(),
            readiness_snapshot=snapshot,
        )


def test_reconciliation_result_cannot_claim_trading_authority() -> None:
    registry = _market_registry()
    snapshot = _market_snapshot(
        registry=registry,
        telemetry=(_healthy("MASSIVE"), _healthy("DATABENTO")),
    )
    observations = (
        _market_observation(
            provider_id="MASSIVE",
            independence_group="MASSIVE_MARKET_DATA",
        ),
        _market_observation(
            provider_id="DATABENTO",
            independence_group="DATABENTO_MARKET_DATA",
            open_price=100.01,
            close=100.21,
            volume=1_030.0,
        ),
    )
    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_market_request(),
        observations=observations,
        readiness_snapshot=snapshot,
    )

    with pytest.raises(
        DataPlaneReconciliationError,
        match="RECONCILIATION_RESULT_MUST_REMAIN_RESEARCH_ONLY",
    ):
        replace(result, trading_authorized=True)
