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
from daily_alpha.agentic.provider_reliability import (
    DataQualityIncidentKind,
    ProviderReliabilityEngine,
    ProviderReliabilityError,
    ProviderReliabilityPolicy,
)
from daily_alpha.agentic.vendor_adapters import institutional_vendor_registry


BASE = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _third_provider() -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="MARKET_THIRD",
        display_name="Third Fixture Source",
        independence_group="MARKET_THIRD_SOURCE",
        source_version="THIRD_V1",
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


def _registry(*, third: bool = False) -> ProviderRegistry:
    registry = institutional_vendor_registry()
    if third:
        registry.register(_third_provider())
    return registry


def _telemetry(
    provider_id: str,
    as_of: datetime,
    status: SourceHealthStatus = SourceHealthStatus.HEALTHY,
) -> SourceTransportTelemetry:
    return SourceTransportTelemetry(
        provider_id=provider_id,
        observed_at=as_of - timedelta(seconds=5),
        status=status,
        latency_ms=25.0 if status is SourceHealthStatus.HEALTHY else 250.0,
        freshness_seconds=5.0,
        last_success_at=as_of - timedelta(seconds=5),
        reason_code=None if status is SourceHealthStatus.HEALTHY else f"FIXTURE_{status.value}",
    )


def _snapshot(
    *,
    registry: ProviderRegistry,
    as_of: datetime,
    massive: SourceHealthStatus = SourceHealthStatus.HEALTHY,
    databento: SourceHealthStatus = SourceHealthStatus.HEALTHY,
    third: SourceHealthStatus | None = None,
):
    telemetry = [
        _telemetry("MASSIVE", as_of, massive),
        _telemetry("DATABENTO", as_of, databento),
    ]
    if third is not None:
        telemetry.append(_telemetry("MARKET_THIRD", as_of, third))
    return InstitutionalDataPlaneReadinessEngine(registry=registry).evaluate(
        policies=(
            DomainReadinessPolicy(
                domain=DataDomain.MARKET_BARS,
                min_independent_groups=2,
                max_latency_ms=100.0,
                max_freshness_seconds=120,
                required=True,
            ),
        ),
        telemetry=tuple(telemetry),
        as_of=as_of,
    )


def _request(as_of: datetime) -> DataRequest:
    return DataRequest(
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV",
        as_of=as_of,
        subject_type=SubjectType.SECURITY,
        security_id="SEC-AAPL",
    )


def _observation(
    provider_id: str,
    group: str,
    as_of: datetime,
    *,
    open_price: float = 100.0,
    close_price: float = 100.2,
) -> ProviderObservation:
    bar_end = as_of - timedelta(seconds=20)
    return ProviderObservation(
        provider_id=provider_id,
        independence_group=group,
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV",
        subject_key="SECURITY:SEC-AAPL",
        value={
            "timeframe": "1M",
            "bar_start": (bar_end - timedelta(minutes=1)).isoformat(),
            "bar_end": bar_end.isoformat(),
            "open": open_price,
            "high": 100.5,
            "low": 99.8,
            "close": close_price,
            "volume": 1_000.0,
        },
        observed_at=bar_end,
        received_at=bar_end + timedelta(seconds=2),
        source_version="FIXTURE_V1",
        status=EvidenceStatus.COMPLETE,
        confidence=1.0,
    )


def _healthy_result(registry: ProviderRegistry, as_of: datetime):
    snapshot = _snapshot(registry=registry, as_of=as_of)
    observations = (
        _observation("MASSIVE", "MASSIVE_MARKET_DATA", as_of),
        _observation(
            "DATABENTO",
            "DATABENTO_MARKET_DATA",
            as_of,
            open_price=100.01,
            close_price=100.21,
        ),
    )
    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_request(as_of),
        observations=observations,
        readiness_snapshot=snapshot,
    )
    return snapshot, result


def _policy(**overrides: object) -> ProviderReliabilityPolicy:
    values: dict[str, object] = {
        "domain": DataDomain.MARKET_BARS,
        "window_seconds": 86_400,
        "min_runtime_samples": 3,
        "min_healthy_ratio": 0.80,
        "max_observation_exclusion_ratio": 0.10,
    }
    values.update(overrides)
    return ProviderReliabilityPolicy(**values)  # type: ignore[arg-type]


def test_three_clean_samples_produce_pass_scorecards() -> None:
    registry = _registry()
    pairs = [_healthy_result(registry, BASE + timedelta(minutes=index)) for index in range(3)]
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(),
        readiness_history=tuple(pair[0] for pair in pairs),
        reconciliation_history=tuple(pair[1] for pair in pairs),
        as_of=BASE + timedelta(minutes=3),
    )

    assert report.status is ReadinessStatus.PASS
    assert report.incidents == ()
    assert {item.provider_id for item in report.provider_assessments} == {"MASSIVE", "DATABENTO"}
    for assessment in report.provider_assessments:
        assert assessment.status is ReadinessStatus.PASS
        assert assessment.runtime_sample_count == 3
        assert assessment.healthy_ratio == 1.0
        assert assessment.observation_count == 3
        assert assessment.exclusion_ratio == 0.0


def test_low_runtime_health_ratio_blocks_required_market_provider() -> None:
    registry = _registry()
    times = [BASE + timedelta(minutes=index) for index in range(3)]
    snapshots = (
        _snapshot(registry=registry, as_of=times[0]),
        _snapshot(
            registry=registry,
            as_of=times[1],
            massive=SourceHealthStatus.UNAVAILABLE,
        ),
        _snapshot(
            registry=registry,
            as_of=times[2],
            massive=SourceHealthStatus.DEGRADED,
        ),
    )
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(),
        readiness_history=snapshots,
        reconciliation_history=(),
        as_of=BASE + timedelta(minutes=3),
    )

    massive = next(item for item in report.provider_assessments if item.provider_id == "MASSIVE")
    assert massive.healthy_ratio == pytest.approx(1 / 3, abs=1e-6)
    assert massive.status is ReadinessStatus.BLOCKED
    assert report.status is ReadinessStatus.BLOCKED
    assert any("HEALTHY_RATIO_BELOW_POLICY" in item for item in massive.blockers)
    kinds = {item.kind for item in report.incidents if item.provider_id == "MASSIVE"}
    assert DataQualityIncidentKind.RUNTIME_UNAVAILABLE in kinds
    assert DataQualityIncidentKind.RUNTIME_DEGRADED in kinds


def test_insufficient_history_is_warning_not_invented_pass() -> None:
    registry = _registry()
    snapshot, result = _healthy_result(registry, BASE)
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(min_runtime_samples=3),
        readiness_history=(snapshot,),
        reconciliation_history=(result,),
        as_of=BASE + timedelta(minutes=1),
    )

    assert report.status is ReadinessStatus.WARNING
    assert all(item.status is ReadinessStatus.WARNING for item in report.provider_assessments)
    assert all(
        any("INSUFFICIENT_RUNTIME_HISTORY" in warning for warning in item.warnings)
        for item in report.provider_assessments
    )


def test_duplicate_history_is_deduplicated_and_identity_is_order_independent() -> None:
    registry = _registry()
    pairs = [_healthy_result(registry, BASE + timedelta(minutes=index)) for index in range(3)]
    snapshots = tuple(pair[0] for pair in pairs)
    results = tuple(pair[1] for pair in pairs)
    engine = ProviderReliabilityEngine(registry=registry)

    first = engine.evaluate(
        policy=_policy(),
        readiness_history=(*snapshots, snapshots[0]),
        reconciliation_history=(*results, results[0]),
        as_of=BASE + timedelta(minutes=3),
    )
    second = engine.evaluate(
        policy=_policy(),
        readiness_history=tuple(reversed(snapshots)),
        reconciliation_history=tuple(reversed(results)),
        as_of=BASE + timedelta(minutes=3),
    )

    assert first.report_id == second.report_id
    assert all(item.runtime_sample_count == 3 for item in first.provider_assessments)
    assert all(item.observation_count == 3 for item in first.provider_assessments)


def test_future_history_is_ignored_for_historical_reliability() -> None:
    registry = _registry()
    pairs = [_healthy_result(registry, BASE + timedelta(minutes=index)) for index in range(3)]
    future_snapshot = _snapshot(
        registry=registry,
        as_of=BASE + timedelta(days=1),
        massive=SourceHealthStatus.UNAVAILABLE,
    )
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(),
        readiness_history=(*tuple(pair[0] for pair in pairs), future_snapshot),
        reconciliation_history=tuple(pair[1] for pair in pairs),
        as_of=BASE + timedelta(minutes=3),
    )

    massive = next(item for item in report.provider_assessments if item.provider_id == "MASSIVE")
    assert massive.runtime_sample_count == 3
    assert massive.healthy_ratio == 1.0
    assert not any(item.occurred_at > report.as_of for item in report.incidents)


def test_optional_provider_failure_warns_without_blocking_when_core_sources_are_healthy() -> None:
    registry = _registry(third=True)
    snapshots = tuple(
        _snapshot(
            registry=registry,
            as_of=BASE + timedelta(minutes=index),
            third=SourceHealthStatus.DEGRADED,
        )
        for index in range(3)
    )
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(),
        readiness_history=snapshots,
        reconciliation_history=(),
        as_of=BASE + timedelta(minutes=3),
    )

    third = next(item for item in report.provider_assessments if item.provider_id == "MARKET_THIRD")
    assert third.role is ProviderRole.OPTIONAL
    assert third.status is ReadinessStatus.WARNING
    assert third.blockers == ()
    assert report.status is ReadinessStatus.WARNING


def test_unassessed_provider_injection_creates_critical_report_blocker() -> None:
    registry = _registry()
    snapshot = _snapshot(registry=registry, as_of=BASE)
    rogue = _observation("ROGUE", "ROGUE_SOURCE", BASE)
    result = InstitutionalReconciliationGateway(registry=registry).reconcile(
        request=_request(BASE),
        observations=(
            _observation("MASSIVE", "MASSIVE_MARKET_DATA", BASE),
            _observation("DATABENTO", "DATABENTO_MARKET_DATA", BASE),
            rogue,
        ),
        readiness_snapshot=snapshot,
    )
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(min_runtime_samples=1),
        readiness_history=(snapshot,),
        reconciliation_history=(result,),
        as_of=BASE + timedelta(minutes=1),
    )

    rogue_incidents = [item for item in report.incidents if item.provider_id == "ROGUE"]
    assert len(rogue_incidents) == 1
    assert rogue_incidents[0].kind is DataQualityIncidentKind.UNASSESSED_PROVIDER
    assert report.status is ReadinessStatus.BLOCKED
    assert any("UNEXPECTED_PROVIDER_INCIDENT:ROGUE" in item for item in report.blockers)


def test_old_history_outside_window_is_not_counted() -> None:
    registry = _registry()
    old_snapshot = _snapshot(
        registry=registry,
        as_of=BASE - timedelta(days=2),
        massive=SourceHealthStatus.UNAVAILABLE,
    )
    recent = [_healthy_result(registry, BASE + timedelta(minutes=index)) for index in range(3)]
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(window_seconds=86_400),
        readiness_history=(old_snapshot, *tuple(pair[0] for pair in recent)),
        reconciliation_history=tuple(pair[1] for pair in recent),
        as_of=BASE + timedelta(minutes=3),
    )

    massive = next(item for item in report.provider_assessments if item.provider_id == "MASSIVE")
    assert massive.runtime_sample_count == 3
    assert massive.healthy_ratio == 1.0


def test_reliability_report_cannot_claim_trading_authority() -> None:
    registry = _registry()
    pairs = [_healthy_result(registry, BASE + timedelta(minutes=index)) for index in range(3)]
    report = ProviderReliabilityEngine(registry=registry).evaluate(
        policy=_policy(),
        readiness_history=tuple(pair[0] for pair in pairs),
        reconciliation_history=tuple(pair[1] for pair in pairs),
        as_of=BASE + timedelta(minutes=3),
    )

    with pytest.raises(
        ProviderReliabilityError,
        match="PROVIDER_RELIABILITY_MUST_REMAIN_RESEARCH_ONLY",
    ):
        replace(report, trading_authorized=True)
