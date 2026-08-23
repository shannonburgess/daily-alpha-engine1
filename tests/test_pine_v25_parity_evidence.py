from datetime import UTC, datetime, timedelta

from daily_alpha.pine_parity_compare import ReferenceSignal
from daily_alpha.pine_parity_evidence import ParityEvidenceBundle
from daily_alpha.pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_COMMIT,
    PINE_V25_STRATEGY_VERSION,
    DailyBar,
    V25Parameters,
)
from daily_alpha.pine_v25_parity_evidence import evaluate_v25_evidence


def _bar(day: int, close: float) -> DailyBar:
    return DailyBar(
        time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
        open=close - 0.2,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1_000_000,
    )


def _params() -> V25Parameters:
    return V25Parameters(
        entry_len=3,
        exit_len=2,
        structural_exit_len=2,
        atr_len=2,
        efficiency_len=2,
        min_prior_bull_bars=1,
        use_rsi_cap=False,
        use_adx_filter=False,
        use_efficiency_gate=False,
        use_price_floor=False,
        use_earnings_gap_sleeve=False,
        use_failed_breakout_exit=False,
        use_structural_runner_exit=False,
        use_runner_management=False,
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2027, 1, 1, tzinfo=UTC),
        enable_shadow_forward_test=True,
        shadow_forward_start=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _bundle(*, model_id=PINE_V25_MODEL_ID, strategy_version=PINE_V25_STRATEGY_VERSION):
    bars = tuple(_bar(i, 100.0 + i) for i in range(7))
    reference = ReferenceSignal(
        symbol="TEST",
        bar_time=bars[3].time,
        action="ENTRY_LONG",
        price=103.0,
        entry_type="NORMAL_BREAKOUT",
        quantity_units=2,
        source="TRADINGVIEW_PINE",
        source_id="TEST-V25-ENTRY",
    )
    return ParityEvidenceBundle(
        schema_version="2026-08-23-v1",
        source="TRADINGVIEW_PINE",
        source_revision=PINE_V25_SOURCE_COMMIT,
        model_id=model_id,
        strategy_version=strategy_version,
        symbol="TEST",
        bars=bars,
        reference_signals=(reference,),
    )


def test_v25_reference_bundle_matches_close_processed_python_entry_exactly():
    report = evaluate_v25_evidence(_bundle(), _params())

    assert report.exact is True
    assert report.reference_count == 1
    assert report.python_count == 1
    assert report.exact_match_count == 1


def test_v25_evaluator_rejects_sh24_or_wrong_version_evidence():
    try:
        evaluate_v25_evidence(_bundle(model_id="PAPER_SHADOW_V24"), _params())
    except ValueError as exc:
        assert "not SH25 CHALLENGER" in str(exc)
    else:
        raise AssertionError("cross-book parity evidence must fail closed")

    try:
        evaluate_v25_evidence(_bundle(strategy_version="2.4"), _params())
    except ValueError as exc:
        assert "not v2.5" in str(exc)
    else:
        raise AssertionError("wrong SH25 strategy version must fail closed")


def test_v25_reference_difference_is_reported_not_retuned():
    bundle = _bundle()
    mismatched_reference = ReferenceSignal(
        symbol="TEST",
        bar_time=bundle.reference_signals[0].bar_time,
        action="ENTRY_LONG",
        price=103.25,
        entry_type="NORMAL_BREAKOUT",
        quantity_units=2,
        source="TRADINGVIEW_PINE",
        source_id="TEST-V25-ENTRY-MISMATCH",
    )
    changed = ParityEvidenceBundle(
        schema_version=bundle.schema_version,
        source=bundle.source,
        source_revision=bundle.source_revision,
        model_id=bundle.model_id,
        strategy_version=bundle.strategy_version,
        symbol=bundle.symbol,
        bars=bundle.bars,
        reference_signals=(mismatched_reference,),
    )

    report = evaluate_v25_evidence(changed, _params())

    assert report.exact is False
    assert {item.kind for item in report.mismatches} == {"PRICE_MISMATCH"}
