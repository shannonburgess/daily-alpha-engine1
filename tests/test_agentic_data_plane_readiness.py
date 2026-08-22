from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.aws_transport import SourceTransportTelemetry
from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.data_plane_readiness import (
    DataPlaneReadinessError,
    DomainReadinessPolicy,
    InstitutionalDataPlaneReadinessEngine,
    ProviderRuntimeStatus,
)
from daily_alpha.agentic.data_providers import DataDomain, ProviderRole
from daily_alpha.agentic.durable_evidence import SourceHealthStatus
from daily_alpha.agentic.vendor_adapters import institutional_vendor_registry

AS_OF = datetime(2026, 8, 22, 4, 30, tzinfo=UTC)


def _telemetry(
    provider_id: str,
    *,
    status: SourceHealthStatus = SourceHealthStatus.HEALTHY,
    observed_delta_seconds: int = 10,
    freshness_seconds: float = 5.0,
    latency_ms: float = 50.0,
) -> SourceTransportTelemetry:
    observed = AS_OF - timedelta(seconds=observed_delta_seconds)
    return SourceTransportTelemetry(
        provider_id=provider_id,
        observed_at=observed,
        status=status,
        latency_ms=latency_ms,
        freshness_seconds=freshness_seconds,
        last_success_at=observed if status is SourceHealthStatus.HEALTHY else None,
    )


def _market_policy(**overrides: object) -> DomainReadinessPolicy:
    values: dict[str, object] = {
        "domain": DataDomain.MARKET_BARS,
        "min_independent_groups": 2,
        "required_roles": (ProviderRole.PRIMARY, ProviderRole.SECONDARY),
        "max_latency_ms": 250.0,
        "max_freshness_seconds": 120,
        "required": True,
    }
    values.update(overrides)
    return DomainReadinessPolicy(**values)  # type: ignore[arg-type]


def test_two_healthy_independent_market_sources_pass() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    result = engine.evaluate_domain(
        policy=_market_policy(),
        telemetry=(_telemetry("MASSIVE"), _telemetry("DATABENTO")),
        as_of=AS_OF,
    )
    assert result.status is ReadinessStatus.PASS
    assert result.healthy_provider_ids == ("DATABENTO", "MASSIVE")
    assert result.healthy_independence_groups == (
        "DATABENTO_MARKET_DATA",
        "MASSIVE_MARKET_DATA",
    )
    assert result.healthy_roles == (ProviderRole.PRIMARY, ProviderRole.SECONDARY)
    assert not result.blockers and not result.warnings


def test_missing_secondary_blocks_required_market_redundancy() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    result = engine.evaluate_domain(
        policy=_market_policy(),
        telemetry=(_telemetry("MASSIVE"),),
        as_of=AS_OF,
    )
    assert result.status is ReadinessStatus.BLOCKED
    assert any("INSUFFICIENT_HEALTHY_INDEPENDENT_GROUPS" in item for item in result.blockers)
    assert "HEALTHY_REQUIRED_ROLE_MISSING:SECONDARY" in result.blockers
    databento = next(item for item in result.provider_assessments if item.provider_id == "DATABENTO")
    assert databento.status is ProviderRuntimeStatus.MISSING


def test_stale_source_does_not_count_as_healthy_redundancy() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    stale = _telemetry("DATABENTO", observed_delta_seconds=200, freshness_seconds=5)
    result = engine.evaluate_domain(
        policy=_market_policy(),
        telemetry=(_telemetry("MASSIVE"), stale),
        as_of=AS_OF,
    )
    assert result.status is ReadinessStatus.BLOCKED
    databento = next(item for item in result.provider_assessments if item.provider_id == "DATABENTO")
    assert databento.status is ProviderRuntimeStatus.STALE
    assert "FRESHNESS_SLA_EXCEEDED" in databento.reasons


def test_latency_budget_degrades_source_and_removes_it_from_strict_redundancy() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    result = engine.evaluate_domain(
        policy=_market_policy(),
        telemetry=(_telemetry("MASSIVE"), _telemetry("DATABENTO", latency_ms=500.0)),
        as_of=AS_OF,
    )
    assert result.status is ReadinessStatus.BLOCKED
    databento = next(item for item in result.provider_assessments if item.provider_id == "DATABENTO")
    assert databento.status is ProviderRuntimeStatus.DEGRADED
    assert "LATENCY_BUDGET_EXCEEDED" in databento.reasons


def test_future_telemetry_cannot_rescue_historical_readiness() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    old = SourceTransportTelemetry(
        provider_id="DATABENTO",
        observed_at=AS_OF - timedelta(minutes=10),
        status=SourceHealthStatus.HEALTHY,
        latency_ms=50,
        freshness_seconds=0,
        last_success_at=AS_OF - timedelta(minutes=10),
    )
    future = SourceTransportTelemetry(
        provider_id="DATABENTO",
        observed_at=AS_OF + timedelta(minutes=1),
        status=SourceHealthStatus.HEALTHY,
        latency_ms=10,
        freshness_seconds=0,
        last_success_at=AS_OF + timedelta(minutes=1),
    )
    result = engine.evaluate_domain(
        policy=_market_policy(),
        telemetry=(_telemetry("MASSIVE"), old, future),
        as_of=AS_OF,
    )
    databento = next(item for item in result.provider_assessments if item.provider_id == "DATABENTO")
    assert databento.status is ProviderRuntimeStatus.STALE
    assert result.status is ReadinessStatus.BLOCKED


def test_optional_domain_degrades_to_warning_not_platform_block() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    snapshot = engine.evaluate(
        policies=(
            _market_policy(),
            DomainReadinessPolicy(
                domain=DataDomain.NEWS_CATALYSTS,
                min_independent_groups=1,
                required=False,
            ),
        ),
        telemetry=(_telemetry("MASSIVE"), _telemetry("DATABENTO")),
        as_of=AS_OF,
    )
    assert snapshot.status is ReadinessStatus.WARNING
    assert snapshot.blocked_domains == ()
    assert snapshot.warning_domains == (DataDomain.NEWS_CATALYSTS,)
    assert snapshot.healthy_provider_count == 2
    assert snapshot.unavailable_provider_count == 1
    assert snapshot.research_only
    assert not snapshot.trading_authorized and not snapshot.live_trading_enabled


def test_unavailable_required_provider_blocks_platform_snapshot() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    snapshot = engine.evaluate(
        policies=(_market_policy(),),
        telemetry=(
            _telemetry("MASSIVE"),
            _telemetry("DATABENTO", status=SourceHealthStatus.UNAVAILABLE),
        ),
        as_of=AS_OF,
    )
    assert snapshot.status is ReadinessStatus.BLOCKED
    assert snapshot.blocked_domains == (DataDomain.MARKET_BARS,)
    assert snapshot.unavailable_provider_count == 1


def test_snapshot_id_is_input_order_deterministic() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    telemetry = (_telemetry("MASSIVE"), _telemetry("DATABENTO"))
    first = engine.evaluate(policies=(_market_policy(),), telemetry=telemetry, as_of=AS_OF)
    second = engine.evaluate(
        policies=(_market_policy(),), telemetry=tuple(reversed(telemetry)), as_of=AS_OF
    )
    assert first.snapshot_id == second.snapshot_id


def test_duplicate_domain_policy_and_live_authority_fail_closed() -> None:
    engine = InstitutionalDataPlaneReadinessEngine(registry=institutional_vendor_registry())
    policy = _market_policy()
    with pytest.raises(DataPlaneReadinessError, match="DATA_PLANE_DOMAIN_POLICY_DUPLICATE"):
        engine.evaluate(policies=(policy, policy), telemetry=(), as_of=AS_OF)

    snapshot = engine.evaluate(
        policies=(DomainReadinessPolicy(DataDomain.NEWS_CATALYSTS, 1, required=False),),
        telemetry=(),
        as_of=AS_OF,
    )
    with pytest.raises(DataPlaneReadinessError, match="DATA_PLANE_READINESS_MUST_REMAIN_RESEARCH_ONLY"):
        type(snapshot)(
            as_of=snapshot.as_of,
            status=snapshot.status,
            domains=snapshot.domains,
            healthy_provider_count=snapshot.healthy_provider_count,
            degraded_provider_count=snapshot.degraded_provider_count,
            stale_provider_count=snapshot.stale_provider_count,
            unavailable_provider_count=snapshot.unavailable_provider_count,
            blocked_domains=snapshot.blocked_domains,
            warning_domains=snapshot.warning_domains,
            research_only=False,
            trading_authorized=True,
        )
