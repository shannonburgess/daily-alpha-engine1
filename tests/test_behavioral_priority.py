from datetime import UTC, datetime

import pytest

from daily_alpha.behavioral_factors import BehavioralResearchFactors
from daily_alpha.behavioral_priority import (
    CoreExecutionGate,
    CoreGateEvidence,
    CoreGateState,
    apply_behavioral_research_priority,
)


def _factors(*, score=72.0, trading_authorized=False):
    return BehavioralResearchFactors(
        search_acceleration_score=61.0,
        video_attention_acceleration_score=74.0,
        web_traffic_acceleration_score=None,
        cross_source_confirmation=1.0,
        persistence_score=80.0,
        behavioral_change_score=score,
        information_imbalance_score=None,
        source_raw_acceleration=(("GOOGLE_TRENDS", 0.2), ("YOUTUBE", 0.3)),
        unavailable_reasons=(("WEB_TRAFFIC_ACCELERATION_SCORE", "SOURCE_UNAVAILABLE"),),
        trading_authorized=trading_authorized,
    )


def _gates(**overrides):
    states = {gate: CoreGateState.PASS for gate in CoreExecutionGate}
    for name, state in overrides.items():
        states[CoreExecutionGate[name]] = state
    return tuple(CoreGateEvidence(gate=gate, state=states[gate]) for gate in CoreExecutionGate)


def test_priority_overlay_is_bounded_and_research_only():
    result = apply_behavioral_research_priority(
        ticker="nvda",
        as_of=datetime(2026, 8, 20, 20, tzinfo=UTC),
        base_research_priority=70.0,
        requested_adjustment=12.0,
        max_abs_adjustment=5.0,
        factors=_factors(),
        core_gates=_gates(),
    )

    assert result.ticker == "NVDA"
    assert result.applied_adjustment == 5.0
    assert result.research_priority == 75.0
    assert result.status == "RESEARCH_PRIORITY_ADJUSTED"
    assert result.core_execution_gates_all_pass is True
    assert result.blocking_core_gates == ()
    assert result.execution_gate_override is False
    assert result.research_only is True
    assert result.promotion_authorized is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_priority_overlay_cannot_turn_failed_core_gates_into_execution_permission():
    result = apply_behavioral_research_priority(
        ticker="NVDA",
        as_of=datetime(2026, 8, 20, 20, tzinfo=UTC),
        base_research_priority=60.0,
        requested_adjustment=4.0,
        max_abs_adjustment=5.0,
        factors=_factors(),
        core_gates=_gates(
            LIQUIDITY=CoreGateState.BLOCKED,
            ORATS=CoreGateState.SOURCE_UNAVAILABLE,
        ),
    )

    assert result.research_priority == 64.0
    assert result.blocking_core_gates == ("ORATS", "LIQUIDITY")
    assert result.core_execution_gates_all_pass is False
    assert result.execution_gate_override is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False
    liquidity = next(row for row in result.core_gates if row.gate == CoreExecutionGate.LIQUIDITY)
    orats = next(row for row in result.core_gates if row.gate == CoreExecutionGate.ORATS)
    assert liquidity.state == CoreGateState.BLOCKED
    assert orats.state == CoreGateState.SOURCE_UNAVAILABLE


def test_unavailable_composite_score_cannot_adjust_research_priority():
    result = apply_behavioral_research_priority(
        ticker="NFLX",
        as_of=datetime(2026, 8, 20, 20, tzinfo=UTC),
        base_research_priority=55.0,
        requested_adjustment=5.0,
        max_abs_adjustment=5.0,
        factors=_factors(score=None),
        core_gates=_gates(),
    )

    assert result.applied_adjustment == 0.0
    assert result.research_priority == 55.0
    assert result.status == "NO_PRIORITY_ADJUSTMENT"
    assert result.reason == "BEHAVIORAL_CHANGE_SCORE_UNAVAILABLE"


def test_priority_overlay_requires_complete_core_gate_evidence():
    incomplete = tuple(
        CoreGateEvidence(gate=gate, state=CoreGateState.PASS)
        for gate in CoreExecutionGate
        if gate != CoreExecutionGate.PORTFOLIO_RISK
    )
    with pytest.raises(ValueError, match="INCOMPLETE_CORE_EXECUTION_GATE_SET"):
        apply_behavioral_research_priority(
            ticker="NVDA",
            as_of=datetime(2026, 8, 20, 20, tzinfo=UTC),
            base_research_priority=50.0,
            requested_adjustment=2.0,
            max_abs_adjustment=5.0,
            factors=_factors(),
            core_gates=incomplete,
        )


def test_priority_overlay_rejects_behavioral_trade_authorization():
    with pytest.raises(ValueError, match="BEHAVIORAL_PRIORITY_TRADING_AUTHORIZATION_REJECTED"):
        apply_behavioral_research_priority(
            ticker="NVDA",
            as_of=datetime(2026, 8, 20, 20, tzinfo=UTC),
            base_research_priority=50.0,
            requested_adjustment=2.0,
            max_abs_adjustment=5.0,
            factors=_factors(trading_authorized=True),
            core_gates=_gates(),
        )
