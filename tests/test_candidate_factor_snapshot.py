from __future__ import annotations

import json
from dataclasses import replace

import pytest

from daily_alpha.candidate_factor_snapshot import (
    CANDIDATE_FACTOR_ARTIFACT_SCHEMA,
    CANDIDATE_FACTOR_SNAPSHOT_SCHEMA,
    build_candidate_factor_snapshot,
    write_candidate_factor_snapshots,
)
from daily_alpha.candidates import CandidateAssessment, CandidateBucket
from daily_alpha.ovtlyr import ClassifiedRecord, OvtlyrRecord, OvtlyrStatus


def _classified(symbol: str = "NFLX") -> ClassifiedRecord:
    return ClassifiedRecord(
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


def _source(symbol: str = "NFLX") -> OvtlyrRecord:
    return OvtlyrRecord(
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


def _candidate(symbol: str = "NFLX") -> CandidateAssessment:
    return CandidateAssessment(
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


def test_snapshot_maps_observed_candidate_evidence_without_authorizing_trades() -> None:
    snapshot = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=_source(),
        classified=_classified(),
        candidate=_candidate(),
    )

    factors = snapshot.vector.factors
    assert factors["momentum"] == 1.0
    assert factors["trendability"] == 1.0
    assert factors["liquidity_capacity"] == 1.0
    assert factors["sector_industry_leadership"] == 0.5
    assert factors["options_confirmation"] == pytest.approx(0.85)

    assert snapshot.schema_version == CANDIDATE_FACTOR_SNAPSHOT_SCHEMA
    assert len(snapshot.snapshot_id) == 64
    assert len(snapshot.weights_hash) == 64
    assert snapshot.as_of == "2026-08-18T20:00:00+00:00"
    assert snapshot.availability["momentum"] is True
    assert snapshot.availability["trendability"] is True
    assert snapshot.availability["liquidity_capacity"] is True
    assert snapshot.availability["sector_industry_leadership"] is True
    assert snapshot.availability["options_confirmation"] is True
    assert snapshot.availability["relative_strength"] is False
    assert snapshot.availability["volatility_quality"] is False
    assert snapshot.availability["catalyst_state"] is False
    assert snapshot.availability["breadth_regime"] is False
    assert snapshot.weighted_coverage == pytest.approx(0.8)
    assert snapshot.research_only is True
    assert snapshot.trading_authorized is False
    assert snapshot.live_trading_enabled is False
    assert snapshot.factor_score.trading_authorized is False


def test_snapshot_identity_is_deterministic_and_evidence_sensitive() -> None:
    first = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=_source(),
        classified=_classified(),
        candidate=_candidate(),
    )
    same = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00+00:00",
        source=_source(),
        classified=_classified(),
        candidate=_candidate(),
    )
    changed = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=_source(),
        classified=_classified(),
        candidate=replace(_candidate(), sector_net_score=10),
    )

    assert first.snapshot_id == same.snapshot_id
    assert first.weights_hash == same.weights_hash
    assert changed.snapshot_id != first.snapshot_id


def test_missing_option_and_liquidity_evidence_stays_explicitly_unavailable() -> None:
    source = OvtlyrRecord(
        symbol="NFLX",
        signal="BUY",
        sector="Communication Services",
        trend="UPTREND",
        momentum="ACCELERATING",
        partial_data=True,
    )
    candidate = CandidateAssessment(
        symbol="NFLX",
        ovtlyr_status=OvtlyrStatus.EMERGING.value,
        bucket=CandidateBucket.DATA_ERROR,
        score=50.0,
        instrument_selected="NONE",
        fallback_reason="DATA_ERROR",
        sector="Communication Services",
        sector_net_score=-10,
        pine_entry=False,
        risk_gate_passed=True,
        optionable=True,
    )

    snapshot = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=source,
        classified=_classified(),
        candidate=candidate,
    )

    assert snapshot.availability["liquidity_capacity"] is False
    assert snapshot.availability["options_confirmation"] is False
    assert "liquidity_capacity" in snapshot.unavailable_factors
    assert "options_confirmation" in snapshot.unavailable_factors
    assert snapshot.vector.factors["sector_industry_leadership"] == -0.25


def test_symbol_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="CANDIDATE_FACTOR_SYMBOL_MISMATCH"):
        build_candidate_factor_snapshot(
            as_of="2026-08-18T20:00:00Z",
            source=_source("NFLX"),
            classified=_classified("NFLX"),
            candidate=_candidate("META"),
        )


def test_naive_factor_timestamp_fails_closed() -> None:
    with pytest.raises(ValueError, match="CANDIDATE_FACTOR_AS_OF_MUST_BE_TIMEZONE_AWARE"):
        build_candidate_factor_snapshot(
            as_of="2026-08-18T20:00:00",
            source=_source(),
            classified=_classified(),
            candidate=_candidate(),
        )


def test_snapshot_artifact_preserves_research_only_boundary(tmp_path) -> None:
    snapshot = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=_source(),
        classified=_classified(),
        candidate=_candidate(),
    )
    path = write_candidate_factor_snapshots(tmp_path / "candidate_factors.json", [snapshot])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == CANDIDATE_FACTOR_ARTIFACT_SCHEMA
    assert len(payload["snapshot_set_id"]) == 64
    assert payload["count"] == 1
    assert payload["research_only"] is True
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["snapshots"][0]["symbol"] == "NFLX"
    assert payload["snapshots"][0]["snapshot_id"] == snapshot.snapshot_id
    assert payload["snapshots"][0]["weighted_coverage"] == pytest.approx(0.8)


def test_snapshot_set_identity_is_order_independent(tmp_path) -> None:
    nflx = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=_source("NFLX"),
        classified=_classified("NFLX"),
        candidate=_candidate("NFLX"),
    )
    meta = build_candidate_factor_snapshot(
        as_of="2026-08-18T20:00:00Z",
        source=_source("META"),
        classified=_classified("META"),
        candidate=_candidate("META"),
    )

    first_path = write_candidate_factor_snapshots(tmp_path / "first.json", [nflx, meta])
    second_path = write_candidate_factor_snapshots(tmp_path / "second.json", [meta, nflx])
    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first["snapshot_set_id"] == second["snapshot_set_id"]
    assert first["snapshots"] == second["snapshots"]
