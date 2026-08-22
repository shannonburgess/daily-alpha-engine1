from datetime import UTC, datetime, timedelta
import math
import statistics

import pytest

from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.data_providers import DataDomain
from daily_alpha.agentic.feature_store import (
    DailyBarFeatureEngine,
    FeatureConflictError,
    FeatureDefinition,
    FeatureRegistry,
    FeatureSourceFamily,
    FeatureStoreError,
    FeatureValue,
    InMemoryFeatureStore,
)
from daily_alpha.agentic.market_reconciliation import CanonicalMarketState

SECURITY_ID = "DAI-SEC-0001"
START = datetime(2025, 11, 1, 21, 0, tzinfo=UTC)


def _state(
    index: int,
    *,
    status: ReadinessStatus = ReadinessStatus.PASS,
    close: float | None = None,
    as_of: datetime | None = None,
) -> CanonicalMarketState:
    bar_end = START + timedelta(days=index + 1)
    bar_start = bar_end - timedelta(days=1)
    price = close if close is not None else 100.0 + index
    canonical_value = None
    provider_id = None
    group = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    if status is ReadinessStatus.BLOCKED:
        blockers = ("TEST_BLOCKED_MARKET_STATE",)
    else:
        canonical_value = {
            "security_id": SECURITY_ID,
            "timeframe": "1D",
            "bar_start": bar_start.isoformat(),
            "bar_end": bar_end.isoformat(),
            "open": price - 0.5,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1_000_000.0 + index * 1_000.0,
        }
        provider_id = "PRIMARY_A"
        group = "GROUP_A"
        if status is ReadinessStatus.WARNING:
            warnings = ("TEST_DEGRADED_MARKET_STATE",)
    return CanonicalMarketState(
        security_id=SECURITY_ID,
        domain=DataDomain.MARKET_BARS,
        metric="OHLCV_1D",
        as_of=as_of or bar_end,
        status=status,
        canonical_provider_id=provider_id,
        canonical_independence_group=group,
        canonical_value=canonical_value,
        observation_ids=(f"obs-{index}",),
        selected_provider_ids=((provider_id,) if provider_id else ()),
        independence_groups=((group,) if group else ()),
        blockers=blockers,
        warnings=warnings,
    )


def _states(count: int = 260) -> tuple[CanonicalMarketState, ...]:
    return tuple(_state(index) for index in range(count))


def _feature(bundle, key: str):
    return next(item for item in bundle.features if item.feature_key == key)


def test_feature_definition_identity_is_parameter_order_independent():
    first = FeatureDefinition(
        feature_key="TEST_FEATURE",
        version="V1",
        calculator_id="TEST",
        source_family=FeatureSourceFamily.MARKET,
        lookback_bars=2,
        output_unit="RATIO",
        parameters={"periods": 5, "annualization": 252},
    )
    second = FeatureDefinition(
        feature_key="TEST_FEATURE",
        version="V1",
        calculator_id="TEST",
        source_family=FeatureSourceFamily.MARKET,
        lookback_bars=2,
        output_unit="RATIO",
        parameters={"annualization": 252, "periods": 5},
    )
    assert first.definition_id == second.definition_id
    assert first.parameters == second.parameters


def test_feature_registry_blocks_silent_same_version_redefinition():
    first = FeatureDefinition(
        "TEST_FEATURE", "V1", "TEST", FeatureSourceFamily.MARKET, 2, "RATIO"
    )
    registry = FeatureRegistry((first,))
    conflicting = FeatureDefinition(
        "TEST_FEATURE", "V1", "TEST", FeatureSourceFamily.MARKET, 3, "RATIO"
    )
    with pytest.raises(FeatureStoreError, match="FEATURE_DEFINITION_CONFLICT"):
        registry.register(conflicting)


def test_daily_feature_engine_computes_reproducible_core_features():
    states = _states()
    as_of = states[-1].as_of
    bundle = DailyBarFeatureEngine().compute(states, as_of=as_of)

    assert bundle.status is ReadinessStatus.PASS
    assert _feature(bundle, "RETURN_1D").value == pytest.approx(359.0 / 358.0 - 1.0)
    assert _feature(bundle, "RETURN_5D").value == pytest.approx(359.0 / 354.0 - 1.0)
    assert _feature(bundle, "RETURN_20D").value == pytest.approx(359.0 / 339.0 - 1.0)

    last_20_closes = [100.0 + index for index in range(240, 260)]
    assert _feature(bundle, "SMA_20D").value == pytest.approx(
        sum(last_20_closes) / 20.0
    )
    assert _feature(bundle, "ATR_14D").value == pytest.approx(2.0)

    last_21_closes = [100.0 + index for index in range(239, 260)]
    log_returns = [
        math.log(last_21_closes[index] / last_21_closes[index - 1])
        for index in range(1, len(last_21_closes))
    ]
    expected_vol = statistics.pstdev(log_returns) * math.sqrt(252.0)
    assert _feature(bundle, "REALIZED_VOL_20D").value == pytest.approx(expected_vol)

    expected_volume = sum(1_000_000.0 + index * 1_000.0 for index in range(240, 260)) / 20.0
    assert _feature(bundle, "AVG_VOLUME_20D").value == pytest.approx(expected_volume)
    assert _feature(bundle, "HIGH_POSITION_252D").value == pytest.approx(359.0 / 360.0)


def test_feature_input_lineage_matches_definition_lookback():
    states = _states()
    bundle = DailyBarFeatureEngine().compute(states, as_of=states[-1].as_of)
    expected = {
        "RETURN_1D": 2,
        "RETURN_5D": 6,
        "RETURN_20D": 21,
        "SMA_10D": 10,
        "SMA_20D": 20,
        "SMA_50D": 50,
        "ATR_14D": 15,
        "REALIZED_VOL_20D": 21,
        "AVG_VOLUME_20D": 20,
        "HIGH_POSITION_252D": 252,
    }
    for feature_key, count in expected.items():
        assert len(_feature(bundle, feature_key).input_state_ids) == count


def test_insufficient_history_blocks_required_features_and_bundle():
    states = _states(12)
    bundle = DailyBarFeatureEngine().compute(states, as_of=states[-1].as_of)
    assert bundle.status is ReadinessStatus.BLOCKED
    assert _feature(bundle, "RETURN_5D").status is ReadinessStatus.PASS
    assert _feature(bundle, "SMA_20D").status is ReadinessStatus.BLOCKED
    assert _feature(bundle, "HIGH_POSITION_252D").status is ReadinessStatus.BLOCKED
    assert _feature(bundle, "SMA_20D").value is None
    assert _feature(bundle, "SMA_20D").blockers == ("INSUFFICIENT_DAILY_BARS:12<20",)


def test_warning_input_only_propagates_to_features_that_use_that_bar():
    states = list(_states())
    states[-3] = _state(257, status=ReadinessStatus.WARNING)
    bundle = DailyBarFeatureEngine().compute(tuple(states), as_of=states[-1].as_of)

    assert bundle.status is ReadinessStatus.WARNING
    assert _feature(bundle, "RETURN_1D").status is ReadinessStatus.PASS
    assert _feature(bundle, "RETURN_5D").status is ReadinessStatus.WARNING
    assert _feature(bundle, "SMA_20D").status is ReadinessStatus.WARNING
    assert _feature(bundle, "RETURN_5D").warnings[0].startswith("DEGRADED_MARKET_INPUT:")


def test_blocked_market_state_is_excluded_and_recorded():
    states = list(_states())
    blocked = _state(100, status=ReadinessStatus.BLOCKED)
    states[100] = blocked
    bundle = DailyBarFeatureEngine().compute(tuple(states), as_of=states[-1].as_of)

    assert bundle.status is ReadinessStatus.WARNING
    assert blocked.state_id in bundle.excluded_market_state_ids
    assert blocked.state_id not in bundle.market_state_ids
    assert _feature(bundle, "SMA_50D").status is ReadinessStatus.PASS


def test_future_market_state_is_rejected_before_feature_computation():
    states = list(_states())
    as_of = states[-1].as_of
    states.append(_state(260, as_of=as_of + timedelta(days=1)))
    with pytest.raises(FeatureStoreError, match="FUTURE_MARKET_STATE_NOT_ALLOWED_IN_FEATURE"):
        DailyBarFeatureEngine().compute(tuple(states), as_of=as_of)


def test_conflicting_duplicate_canonical_bar_fails_closed():
    states = list(_states())
    conflicting = _state(259, close=500.0, as_of=states[-1].as_of)
    states.append(conflicting)
    with pytest.raises(FeatureStoreError, match="CONFLICTING_CANONICAL_BAR"):
        DailyBarFeatureEngine().compute(tuple(states), as_of=states[-1].as_of)


def test_feature_bundle_identity_is_input_order_independent():
    states = _states()
    engine = DailyBarFeatureEngine()
    left = engine.compute(states, as_of=states[-1].as_of)
    right = engine.compute(tuple(reversed(states)), as_of=states[-1].as_of)
    assert left.bundle_id == right.bundle_id
    assert [item.feature_value_id for item in left.features] == [
        item.feature_value_id for item in right.features
    ]


def test_feature_store_is_idempotent_but_rejects_logical_rewrite():
    definition = FeatureDefinition(
        "TEST_FEATURE", "V1", "TEST", FeatureSourceFamily.MARKET, 2, "RATIO"
    )
    as_of = START + timedelta(days=10)
    first = FeatureValue(
        security_id=SECURITY_ID,
        feature_key=definition.feature_key,
        as_of=as_of,
        definition_id=definition.definition_id,
        definition_version=definition.version,
        output_unit=definition.output_unit,
        status=ReadinessStatus.PASS,
        value=1.0,
        input_state_ids=("state-a", "state-b"),
    )
    store = InMemoryFeatureStore()
    assert store.put(first) == store.put(first)

    conflicting = FeatureValue(
        security_id=SECURITY_ID,
        feature_key=definition.feature_key,
        as_of=as_of,
        definition_id=definition.definition_id,
        definition_version=definition.version,
        output_unit=definition.output_unit,
        status=ReadinessStatus.PASS,
        value=2.0,
        input_state_ids=("state-a", "state-b"),
    )
    with pytest.raises(FeatureConflictError, match="FEATURE_IMMUTABILITY_VIOLATION"):
        store.put(conflicting)


def test_feature_store_latest_is_point_in_time():
    definition = FeatureDefinition(
        "TEST_FEATURE", "V1", "TEST", FeatureSourceFamily.MARKET, 2, "RATIO"
    )
    store = InMemoryFeatureStore()
    early_time = START + timedelta(days=10)
    late_time = START + timedelta(days=20)
    early = FeatureValue(
        SECURITY_ID,
        definition.feature_key,
        early_time,
        definition.definition_id,
        definition.version,
        definition.output_unit,
        ReadinessStatus.PASS,
        1.0,
        ("state-early",),
    )
    late = FeatureValue(
        SECURITY_ID,
        definition.feature_key,
        late_time,
        definition.definition_id,
        definition.version,
        definition.output_unit,
        ReadinessStatus.PASS,
        2.0,
        ("state-late",),
    )
    store.put(early)
    store.put(late)
    assert store.latest(
        security_id=SECURITY_ID,
        feature_key="TEST_FEATURE",
        as_of=early_time + timedelta(days=1),
    ) == early
    assert store.latest(
        security_id=SECURITY_ID,
        feature_key="TEST_FEATURE",
        as_of=late_time,
    ) == late


def test_feature_value_cannot_enable_trading_or_live_execution():
    definition = FeatureDefinition(
        "TEST_FEATURE", "V1", "TEST", FeatureSourceFamily.MARKET, 2, "RATIO"
    )
    with pytest.raises(FeatureStoreError, match="FEATURE_VALUE_MUST_REMAIN_RESEARCH_ONLY"):
        FeatureValue(
            security_id=SECURITY_ID,
            feature_key=definition.feature_key,
            as_of=START,
            definition_id=definition.definition_id,
            definition_version=definition.version,
            output_unit=definition.output_unit,
            status=ReadinessStatus.PASS,
            value=1.0,
            input_state_ids=("state-a",),
            live_trading_enabled=True,
        )


def test_blocked_feature_cannot_carry_a_value():
    definition = FeatureDefinition(
        "TEST_FEATURE", "V1", "TEST", FeatureSourceFamily.MARKET, 2, "RATIO"
    )
    with pytest.raises(FeatureStoreError, match="BLOCKED_FEATURE_CANNOT_HAVE_VALUE"):
        FeatureValue(
            security_id=SECURITY_ID,
            feature_key=definition.feature_key,
            as_of=START,
            definition_id=definition.definition_id,
            definition_version=definition.version,
            output_unit=definition.output_unit,
            status=ReadinessStatus.BLOCKED,
            value=1.0,
            input_state_ids=(),
            blockers=("NO_DATA",),
        )
