from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.contracts import EvidenceStatus
from daily_alpha.agentic.data_providers import (
    DataDomain,
    DataProviderError,
    DataRequest,
    ProviderCapability,
    ProviderDefinition,
    ProviderObservation,
    ProviderRegistry,
    ProviderRole,
    RedundancyPolicy,
    SubjectType,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _capability(
    *,
    domain: DataDomain = DataDomain.MARKET_BARS,
    role: ProviderRole = ProviderRole.PRIMARY,
) -> ProviderCapability:
    return ProviderCapability(
        domain=domain,
        role=role,
        cadence_seconds=60,
        max_freshness_seconds=120,
        supports_point_in_time_history=True,
    )


def _provider(
    provider_id: str,
    group: str,
    *,
    domain: DataDomain = DataDomain.MARKET_BARS,
    role: ProviderRole = ProviderRole.PRIMARY,
) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id=provider_id,
        display_name=provider_id,
        independence_group=group,
        source_version="V1",
        capabilities=(_capability(domain=domain, role=role),),
    )


def _request() -> DataRequest:
    return DataRequest(
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1M",
        as_of=NOW,
        subject_type=SubjectType.SECURITY,
        security_id="DAI-SEC-0001",
        start_at=NOW - timedelta(minutes=10),
        end_at=NOW - timedelta(minutes=1),
    )


def test_security_request_uses_permanent_security_id_not_ticker():
    request = _request()
    assert request.subject_key == "SECURITY:DAI-SEC-0001"
    assert request.request_id == _request().request_id


def test_request_rejects_future_end_boundary_and_mixed_subjects():
    with pytest.raises(DataProviderError, match="DATA_REQUEST_END_AFTER_AS_OF"):
        DataRequest(
            domain=DataDomain.MARKET_BARS,
            metric="OHLCV_1M",
            as_of=NOW,
            subject_type=SubjectType.SECURITY,
            security_id="DAI-SEC-0001",
            end_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(DataProviderError, match="SECURITY_REQUEST_REQUIRES_ONLY_SECURITY_ID"):
        DataRequest(
            domain=DataDomain.MARKET_BARS,
            metric="OHLCV_1M",
            as_of=NOW,
            subject_type=SubjectType.SECURITY,
            security_id="DAI-SEC-0001",
            global_series_id="SPX",
        )


def test_global_request_supports_macro_series_without_fake_security():
    request = DataRequest(
        domain=DataDomain.MACRO,
        metric="RATE",
        as_of=NOW,
        subject_type=SubjectType.GLOBAL,
        global_series_id="US10Y",
    )
    assert request.subject_key == "GLOBAL:US10Y"


def test_provider_registry_blocks_silent_redefinition():
    registry = ProviderRegistry((_provider("FEED_A", "UPSTREAM_A"),))
    with pytest.raises(DataProviderError, match="PROVIDER_DEFINITION_CONFLICT:FEED_A"):
        registry.register(_provider("FEED_A", "UPSTREAM_B"))


def test_redundancy_counts_independent_upstreams_not_api_adapters():
    registry = ProviderRegistry(
        (
            _provider("API_A", "UPSTREAM_X", role=ProviderRole.PRIMARY),
            _provider("API_B", "UPSTREAM_X", role=ProviderRole.SECONDARY),
        )
    )
    assessment = registry.assess_coverage(
        RedundancyPolicy(
            domain=DataDomain.MARKET_BARS,
            min_independent_groups=2,
            required_roles=(ProviderRole.PRIMARY,),
        )
    )
    assert assessment.complete is False
    assert assessment.independence_groups == ("UPSTREAM_X",)
    assert assessment.blockers == (
        "INSUFFICIENT_INDEPENDENT_PROVIDER_GROUPS:MARKET_BARS:1<2",
    )


def test_redundancy_passes_with_independent_primary_and_secondary_groups():
    registry = ProviderRegistry(
        (
            _provider("FEED_A", "UPSTREAM_A", role=ProviderRole.PRIMARY),
            _provider("FEED_B", "UPSTREAM_B", role=ProviderRole.SECONDARY),
        )
    )
    assessment = registry.assess_coverage(
        RedundancyPolicy(
            domain=DataDomain.MARKET_BARS,
            min_independent_groups=2,
            required_roles=(ProviderRole.PRIMARY, ProviderRole.SECONDARY),
        )
    )
    assert assessment.complete is True
    assert assessment.blockers == ()


def test_observation_must_match_request_and_cannot_leak_future_data():
    request = _request()
    observation = ProviderObservation(
        provider_id="FEED_A",
        independence_group="UPSTREAM_A",
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1M",
        subject_key=request.subject_key,
        value={"close": 100.0},
        observed_at=NOW - timedelta(minutes=2),
        received_at=NOW - timedelta(minutes=1),
        source_version="V1",
    )
    observation.validate_against(request)

    future = ProviderObservation(
        provider_id="FEED_A",
        independence_group="UPSTREAM_A",
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1M",
        subject_key=request.subject_key,
        value={"close": 101.0},
        observed_at=NOW + timedelta(seconds=1),
        received_at=NOW + timedelta(seconds=2),
        source_version="V1",
    )
    with pytest.raises(DataProviderError, match="FUTURE_PROVIDER_OBSERVATION_NOT_ALLOWED"):
        future.validate_against(request)


def test_observation_identity_is_deterministic_and_provenance_order_independent():
    first = ProviderObservation(
        provider_id="FEED_A",
        independence_group="UPSTREAM_A",
        domain=DataDomain.MARKET_QUOTES,
        metric="NBBO",
        subject_key="SECURITY:DAI-SEC-0001",
        value={"bid": 99.9, "ask": 100.1},
        observed_at=NOW - timedelta(seconds=2),
        received_at=NOW - timedelta(seconds=1),
        source_version="V1",
        provenance={"venue": "SIP", "sequence": "10"},
    )
    second = ProviderObservation(
        provider_id="FEED_A",
        independence_group="UPSTREAM_A",
        domain=DataDomain.MARKET_QUOTES,
        metric="NBBO",
        subject_key="SECURITY:DAI-SEC-0001",
        value={"ask": 100.1, "bid": 99.9},
        observed_at=NOW - timedelta(seconds=2),
        received_at=NOW - timedelta(seconds=1),
        source_version="V1",
        provenance={"sequence": "10", "venue": "SIP"},
    )
    assert first.observation_id == second.observation_id


def test_bad_provider_data_has_explicit_status_not_silent_missing_value():
    observation = ProviderObservation(
        provider_id="FEED_A",
        independence_group="UPSTREAM_A",
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1M",
        subject_key="SECURITY:DAI-SEC-0001",
        value={"error": "timeout"},
        observed_at=NOW - timedelta(minutes=1),
        received_at=NOW,
        source_version="V1",
        status=EvidenceStatus.SOURCE_UNAVAILABLE,
        confidence=0.0,
        reason_code="UPSTREAM_TIMEOUT",
    )
    assert observation.status is EvidenceStatus.SOURCE_UNAVAILABLE
    assert observation.reason_code == "UPSTREAM_TIMEOUT"


def test_provider_contract_cannot_authorize_trading():
    with pytest.raises(DataProviderError, match="PROVIDER_DEFINITION_MUST_REMAIN_RESEARCH_ONLY"):
        ProviderDefinition(
            provider_id="FEED_A",
            display_name="Feed A",
            independence_group="UPSTREAM_A",
            source_version="V1",
            capabilities=(_capability(),),
            live_trading_enabled=True,
        )
