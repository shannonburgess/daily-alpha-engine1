from __future__ import annotations

import json
from dataclasses import replace

import pytest

from daily_alpha.candidate_factor_snapshot import build_candidate_factor_snapshot
from daily_alpha.candidates import CandidateAssessment, CandidateBucket
from daily_alpha.factor_forward_returns import (
    FACTOR_FORWARD_RETURN_SET_SCHEMA,
    FrozenForwardReturn,
    bind_forward_return,
    write_factor_forward_return_bindings,
)
from daily_alpha.ovtlyr import ClassifiedRecord, OvtlyrRecord, OvtlyrStatus


def _snapshot(symbol: str = "NFLX"):
    source = OvtlyrRecord(
        symbol=symbol,
        signal="BUY",
        signal_date="2026-08-18",
        sector="Communication Services",
        industry="Entertainment",
        trend="UPTREND",
        momentum="ACCELERATING",
        optionable=True,
        price=100.0,
        average_volume=5_000_000,
    )
    classified = ClassifiedRecord(
        symbol=symbol,
        status=OvtlyrStatus.EMERGING,
        display_label="🔥 EMERGING",
        signal="BUY",
        previous_signal="BUY",
        signal_date="2026-08-18",
        sector="Communication Services",
        industry="Entertainment",
        trend="UPTREND",
        momentum="ACCELERATING",
        optionable=True,
        reason="test",
    )
    candidate = CandidateAssessment(
        symbol=symbol,
        ovtlyr_status=OvtlyrStatus.EMERGING.value,
        bucket=CandidateBucket.OPTION_SETUP,
        score=91.0,
        instrument_selected="OPTION",
        fallback_reason="QUALIFIED_OPTION",
        sector="Communication Services",
        sector_net_score=20,
        pine_entry=True,
        risk_gate_passed=True,
        optionable=True,
        selected_expiration="2026-12-18",
        selected_strike=100.0,
        selected_delta=0.55,
        selected_spread_pct=0.04,
        unusual_options_activity=True,
    )
    return build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=source,
        classified=classified,
        candidate=candidate,
    )


def _outcome(snapshot, **changes):
    outcome = FrozenForwardReturn(
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        as_of=snapshot.as_of,
        horizon_bars=20,
        bars_observed=20,
        reference_price=100.0,
        evaluation_price=110.0,
        evaluation_at="2026-09-16T20:00:00Z",
        source_id="TEST_DAILY_CLOSES",
        source_hash="a" * 64,
    )
    return replace(outcome, **changes)


def test_bind_forward_return_uses_snapshot_identity_and_available_factors_only() -> None:
    snapshot = _snapshot()
    outcome = _outcome(snapshot)

    binding = bind_forward_return(snapshot, outcome)

    assert binding.snapshot_id == snapshot.snapshot_id
    assert binding.outcome_id == outcome.outcome_id
    assert binding.forward_return == pytest.approx(0.10)
    assert binding.horizon_bars == 20
    assert len(binding.observations) == 4
    assert {item.factor for item in binding.observations} == {
        "momentum",
        "trendability",
        "liquidity_capacity",
        "sector_industry_leadership",
    }
    assert "options_confirmation" not in {item.factor for item in binding.observations}
    assert all(item.forward_return == pytest.approx(0.10) for item in binding.observations)
    assert all(item.sector == "Communication Services" for item in binding.observations)
    assert binding.trading_authorized is False
    assert binding.live_trading_enabled is False


def test_snapshot_identity_mismatch_fails_closed() -> None:
    snapshot = _snapshot()
    outcome = _outcome(snapshot, snapshot_id="b" * 64)

    with pytest.raises(ValueError, match="FACTOR_FORWARD_SNAPSHOT_ID_MISMATCH"):
        bind_forward_return(snapshot, outcome)


def test_symbol_and_as_of_mismatch_fail_closed() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="FACTOR_FORWARD_SYMBOL_MISMATCH"):
        bind_forward_return(snapshot, _outcome(snapshot, symbol="META"))

    with pytest.raises(ValueError, match="FACTOR_FORWARD_AS_OF_MISMATCH"):
        bind_forward_return(
            snapshot,
            _outcome(snapshot, as_of="2026-08-18T19:59:59Z"),
        )


def test_forward_observation_requires_exact_horizon_and_future_timestamp() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="FACTOR_FORWARD_BAR_COUNT_MISMATCH"):
        _outcome(snapshot, bars_observed=19)

    with pytest.raises(ValueError, match="FACTOR_FORWARD_EVALUATION_NOT_AFTER_SNAPSHOT"):
        _outcome(snapshot, evaluation_at="2026-08-18T20:00:00Z")


def test_forward_observation_requires_source_provenance() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="FACTOR_FORWARD_SOURCE_ID_REQUIRED"):
        _outcome(snapshot, source_id="")

    with pytest.raises(ValueError, match="FACTOR_FORWARD_SOURCE_HASH_INVALID"):
        _outcome(snapshot, source_hash="not-a-hash")


def test_outcome_identity_is_timezone_normalized_and_evidence_sensitive() -> None:
    snapshot = _snapshot()
    first = _outcome(snapshot)
    same = _outcome(
        snapshot,
        as_of="2026-08-18T13:00:00-07:00",
        evaluation_at="2026-09-16T13:00:00-07:00",
    )
    changed = _outcome(snapshot, evaluation_price=111.0)

    assert first.outcome_id == same.outcome_id
    assert changed.outcome_id != first.outcome_id


def test_binding_artifact_is_deterministic_and_research_only(tmp_path) -> None:
    nflx = _snapshot("NFLX")
    meta = _snapshot("META")
    nflx_binding = bind_forward_return(nflx, _outcome(nflx))
    meta_binding = bind_forward_return(meta, _outcome(meta))

    first_path = write_factor_forward_return_bindings(
        tmp_path / "first.json",
        [nflx_binding, meta_binding],
    )
    second_path = write_factor_forward_return_bindings(
        tmp_path / "second.json",
        [meta_binding, nflx_binding],
    )
    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first["schema_version"] == FACTOR_FORWARD_RETURN_SET_SCHEMA
    assert first["binding_set_id"] == second["binding_set_id"]
    assert first["bindings"] == second["bindings"]
    assert first["count"] == 2
    assert first["research_only"] is True
    assert first["trading_authorized"] is False
    assert first["live_trading_enabled"] is False
