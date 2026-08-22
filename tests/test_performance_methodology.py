from __future__ import annotations

from daily_alpha.performance_methodology import (
    BenchmarkSpec,
    CostEvidence,
    OptionMarkPolicy,
    PerformanceBasis,
    PerformanceEvidence,
    PerformanceMethodology,
    QuoteQuality,
    TransactionCostPolicy,
    validate_performance_evidence,
)


def methodology() -> PerformanceMethodology:
    return PerformanceMethodology(
        version="perf-v1",
        effective_at="2026-08-17T19:00:00-07:00",
        valuation_cutoff="16:00:00 America/New_York",
        annualization_min_calendar_days=365,
        benchmark=BenchmarkSpec(
            benchmark_id="SPY_TOTAL_RETURN",
            version="benchmark-v1",
            frozen_at="2026-08-17T19:00:00-07:00",
            total_return=True,
            purpose="Broad U.S. equity reference for the current equity research mandate",
        ),
        cost_policy=TransactionCostPolicy(
            version="cost-v1",
            stock_commission_per_share=0.0,
            stock_slippage_bps=2.0,
            option_commission_per_contract=0.65,
        ),
        option_mark_policy=OptionMarkPolicy.OBSERVED_EXECUTABLE_SIDE,
    )


def evidence(
    *,
    basis: PerformanceBasis = PerformanceBasis.PAPER,
    methodology_version: str = "perf-v1",
    benchmark_id: str = "SPY_TOTAL_RETURN",
    option_exposure: bool = False,
    quote_quality: QuoteQuality | None = None,
    cost_evidence: CostEvidence = CostEvidence.ESTIMATED,
    gross_return: float = 0.12,
    net_return: float = 0.115,
) -> PerformanceEvidence:
    return PerformanceEvidence(
        evidence_id=f"evidence-{basis.value.lower()}",
        methodology_version=methodology_version,
        performance_basis=basis,
        strategy_version="v2.4",
        start_at="2026-01-01T16:00:00-05:00",
        end_at="2026-08-17T16:00:00-04:00",
        valuation_cutoff_at="2026-08-17T16:00:00-04:00",
        benchmark_id=benchmark_id,
        gross_return=gross_return,
        net_return=net_return,
        cost_evidence=cost_evidence,
        option_exposure=option_exposure,
        option_quote_quality=quote_quality,
        source_cutoff_at="2026-08-17T16:00:00-04:00",
        evidence_hash="a" * 64,
    )


def test_valid_single_basis_evidence_passes() -> None:
    ok, reasons = validate_performance_evidence(methodology(), (evidence(),))
    assert ok is True
    assert reasons == ("PERFORMANCE_EVIDENCE_VALID",)


def test_actual_and_paper_cannot_be_mixed() -> None:
    ok, reasons = validate_performance_evidence(
        methodology(),
        (
            evidence(basis=PerformanceBasis.ACTUAL),
            evidence(basis=PerformanceBasis.PAPER),
        ),
    )
    assert ok is False
    assert "MIXED_PERFORMANCE_BASES" in reasons


def test_methodology_and_benchmark_mismatch_fail_closed() -> None:
    ok, reasons = validate_performance_evidence(
        methodology(),
        (evidence(methodology_version="perf-v0", benchmark_id="QQQ_TOTAL_RETURN"),),
    )
    assert ok is False
    assert "METHODOLOGY_VERSION_MISMATCH" in reasons
    assert "BENCHMARK_MISMATCH" in reasons


def test_option_evidence_requires_executable_quote_quality() -> None:
    ok, reasons = validate_performance_evidence(
        methodology(),
        (evidence(option_exposure=True, quote_quality=QuoteQuality.STALE),),
    )
    assert ok is False
    assert "NON_EXECUTABLE_OPTION_MARK" in reasons


def test_estimated_costs_must_change_net_return() -> None:
    ok, reasons = validate_performance_evidence(
        methodology(),
        (evidence(gross_return=0.12, net_return=0.12, cost_evidence=CostEvidence.ESTIMATED),),
    )
    assert ok is False
    assert "ESTIMATED_COSTS_NOT_REFLECTED_IN_NET_RETURN" in reasons


def test_methodology_hash_is_deterministic() -> None:
    first = methodology().methodology_hash
    second = methodology().methodology_hash
    assert len(first) == 64
    assert first == second
