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
from daily_alpha.agentic.market_reconciliation import (
    MarketDataError,
    MarketDataReconciler,
    MarketReconciliationPolicy,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
BAR_START = NOW - timedelta(minutes=2)
BAR_END = NOW - timedelta(minutes=1)


def _definition(provider_id: str, group: str, role: ProviderRole, domain: DataDomain):
    return ProviderDefinition(
        provider_id=provider_id,
        display_name=provider_id,
        independence_group=group,
        source_version="V1",
        capabilities=(
            ProviderCapability(
                domain=domain,
                role=role,
                cadence_seconds=60,
                max_freshness_seconds=180,
                supports_point_in_time_history=True,
            ),
        ),
    )


def _bar_request() -> DataRequest:
    return DataRequest(
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1M",
        as_of=NOW,
        subject_type=SubjectType.SECURITY,
        security_id="DAI-SEC-0001",
    )


def _bar_observation(
    provider_id: str,
    group: str,
    *,
    close: float = 100.0,
    volume: float = 1_000_000.0,
    observed_at: datetime = BAR_END,
    status: EvidenceStatus = EvidenceStatus.COMPLETE,
) -> ProviderObservation:
    return ProviderObservation(
        provider_id=provider_id,
        independence_group=group,
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1M",
        subject_key="SECURITY:DAI-SEC-0001",
        value={
            "timeframe": "1M",
            "bar_start": BAR_START.isoformat(),
            "bar_end": BAR_END.isoformat(),
            "open": 99.9,
            "high": max(100.1, close),
            "low": 99.8,
            "close": close,
            "volume": volume,
        },
        observed_at=observed_at,
        received_at=observed_at + timedelta(seconds=1),
        source_version="V1",
        status=status,
        confidence=1.0 if status is EvidenceStatus.COMPLETE else 0.0,
    )


def _quote_request() -> DataRequest:
    return DataRequest(
        domain=DataDomain.MARKET_QUOTES,
        metric="NBBO",
        as_of=NOW,
        subject_type=SubjectType.SECURITY,
        security_id="DAI-SEC-0001",
    )


def _quote_observation(
    provider_id: str,
    group: str,
    *,
    role_time_offset_ms: int = 0,
    bid: float = 99.99,
    ask: float = 100.01,
) -> ProviderObservation:
    quote_time = NOW - timedelta(seconds=10) + timedelta(milliseconds=role_time_offset_ms)
    return ProviderObservation(
        provider_id=provider_id,
        independence_group=group,
        domain=DataDomain.MARKET_QUOTES,
        metric="NBBO",
        subject_key="SECURITY:DAI-SEC-0001",
        value={
            "quote_time": quote_time.isoformat(),
            "bid": bid,
            "ask": ask,
            "bid_size": 500,
            "ask_size": 600,
            "last": 100.0,
        },
        observed_at=quote_time,
        received_at=quote_time + timedelta(milliseconds=50),
        source_version="V1",
    )


def test_two_independent_agreeing_bars_create_primary_canonical_state():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_BARS),
        )
    )
    state = MarketDataReconciler(registry).reconcile_bar(
        _bar_request(),
        (
            _bar_observation("SECONDARY_B", "GROUP_B", close=100.01),
            _bar_observation("PRIMARY_A", "GROUP_A", close=100.0),
        ),
        policy=MarketReconciliationPolicy(max_price_deviation_bps=5.0),
    )
    assert state.status is ReadinessStatus.PASS
    assert state.canonical_provider_id == "PRIMARY_A"
    assert state.canonical_value["close"] == 100.0
    assert state.independence_groups == ("GROUP_A", "GROUP_B")


def test_two_adapters_from_same_upstream_do_not_satisfy_redundancy():
    registry = ProviderRegistry(
        (
            _definition("API_A", "GROUP_X", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),
            _definition("API_B", "GROUP_X", ProviderRole.SECONDARY, DataDomain.MARKET_BARS),
        )
    )
    state = MarketDataReconciler(registry).reconcile_bar(
        _bar_request(),
        (
            _bar_observation("API_A", "GROUP_X"),
            _bar_observation("API_B", "GROUP_X"),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert state.canonical_value is None
    assert "INSUFFICIENT_INDEPENDENT_MARKET_SOURCES:1<2" in state.blockers


def test_material_price_disagreement_blocks_canonical_bar():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_BARS),
        )
    )
    state = MarketDataReconciler(registry).reconcile_bar(
        _bar_request(),
        (
            _bar_observation("PRIMARY_A", "GROUP_A", close=100.0),
            _bar_observation("SECONDARY_B", "GROUP_B", close=101.0),
        ),
        policy=MarketReconciliationPolicy(max_price_deviation_bps=5.0),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert state.canonical_value is None
    assert "MARKET_BAR_PRICE_CONFLICT:SECONDARY_B:CLOSE" in state.blockers


def test_stale_source_is_excluded_and_visible():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_BARS),
        )
    )
    stale_time = NOW - timedelta(minutes=10)
    stale = _bar_observation("PRIMARY_A", "GROUP_A", observed_at=stale_time)
    fresh = _bar_observation("SECONDARY_B", "GROUP_B")
    state = MarketDataReconciler(registry).reconcile_bar(_bar_request(), (stale, fresh))
    assert state.status is ReadinessStatus.BLOCKED
    assert "MARKET_SOURCE_STALE:PRIMARY_A" in state.warnings
    assert "INSUFFICIENT_INDEPENDENT_MARKET_SOURCES:1<2" in state.blockers


def test_noncomplete_source_is_excluded_not_promoted_to_truth():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_BARS),
        )
    )
    state = MarketDataReconciler(registry).reconcile_bar(
        _bar_request(),
        (
            _bar_observation(
                "PRIMARY_A",
                "GROUP_A",
                status=EvidenceStatus.SOURCE_UNAVAILABLE,
            ),
            _bar_observation("SECONDARY_B", "GROUP_B"),
        ),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "MARKET_SOURCE_EXCLUDED:PRIMARY_A:SOURCE_UNAVAILABLE" in state.warnings


def test_agreeing_quotes_create_canonical_quote_state():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_QUOTES),
            _definition("BROKER_B", "GROUP_B", ProviderRole.BROKER_REFERENCE, DataDomain.MARKET_QUOTES),
        )
    )
    state = MarketDataReconciler(registry).reconcile_quote(
        _quote_request(),
        (
            _quote_observation("PRIMARY_A", "GROUP_A"),
            _quote_observation("BROKER_B", "GROUP_B", role_time_offset_ms=200),
        ),
    )
    assert state.status is ReadinessStatus.PASS
    assert state.canonical_provider_id == "PRIMARY_A"
    assert state.canonical_value["bid"] == 99.99


def test_quote_timestamp_skew_blocks_reconciliation():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_QUOTES),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_QUOTES),
        )
    )
    state = MarketDataReconciler(registry).reconcile_quote(
        _quote_request(),
        (
            _quote_observation("PRIMARY_A", "GROUP_A"),
            _quote_observation("SECONDARY_B", "GROUP_B", role_time_offset_ms=5_000),
        ),
        policy=MarketReconciliationPolicy(max_quote_time_skew_seconds=1.0),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert "MARKET_QUOTE_TIME_SKEW_CONFLICT:SECONDARY_B" in state.blockers


def test_canonical_state_id_is_independent_of_observation_input_order():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_BARS),
        )
    )
    reconciler = MarketDataReconciler(registry)
    first = _bar_observation("PRIMARY_A", "GROUP_A")
    second = _bar_observation("SECONDARY_B", "GROUP_B")
    left = reconciler.reconcile_bar(_bar_request(), (first, second))
    right = reconciler.reconcile_bar(_bar_request(), (second, first))
    assert left.state_id == right.state_id


def test_crossed_quote_is_rejected():
    registry = ProviderRegistry(
        (
            _definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_QUOTES),
            _definition("SECONDARY_B", "GROUP_B", ProviderRole.SECONDARY, DataDomain.MARKET_QUOTES),
        )
    )
    bad = _quote_observation("PRIMARY_A", "GROUP_A", bid=100.1, ask=100.0)
    good = _quote_observation("SECONDARY_B", "GROUP_B")
    state = MarketDataReconciler(registry).reconcile_quote(_quote_request(), (bad, good))
    assert state.status is ReadinessStatus.BLOCKED
    assert any(item.startswith("INVALID_MARKET_QUOTE:PRIMARY_A") for item in state.blockers)


def test_wrong_request_domain_is_rejected():
    registry = ProviderRegistry(
        (_definition("PRIMARY_A", "GROUP_A", ProviderRole.PRIMARY, DataDomain.MARKET_BARS),)
    )
    with pytest.raises(MarketDataError, match="QUOTE_RECONCILIATION_REQUIRES_MARKET_QUOTES_REQUEST"):
        MarketDataReconciler(registry).reconcile_quote(_bar_request(), ())
