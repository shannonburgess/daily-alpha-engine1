from datetime import UTC, datetime

import pytest

from daily_alpha.pine_parity_evidence import (
    PARITY_EVIDENCE_SCHEMA_VERSION,
    evaluate_v24_evidence,
    parse_parity_evidence_bundle,
)
from daily_alpha.pine_v24_parity import V24Parameters


def _params() -> V24Parameters:
    return V24Parameters(
        entry_len=3,
        exit_len=2,
        atr_len=2,
        efficiency_len=2,
        min_prior_bull_bars=1,
        use_rsi_cap=False,
        use_adx_filter=False,
        use_efficiency_gate=False,
        use_price_floor=False,
        use_earnings_gap_sleeve=False,
        use_trend_exit=False,
        use_runner_management=False,
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2027, 1, 1, tzinfo=UTC),
    )


def _bundle(*, reference_price: float = 103.0, model_id: str = "PAPER_SHADOW_V24"):
    return {
        "schema_version": PARITY_EVIDENCE_SCHEMA_VERSION,
        "source": "TRADINGVIEW_EXPORT",
        "source_revision": "sha256:fixture-v24-001",
        "model_id": model_id,
        "strategy_version": "2.4",
        "symbol": "TEST",
        "bars": [
            {
                "time": f"2026-01-0{index + 1}T20:00:00+00:00",
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1_000_000,
            }
            for index, close in enumerate([100.0, 101.0, 102.0, 103.0])
        ],
        "reference_signals": [
            {
                "source_id": "tv-test-entry-1",
                "bar_time": "2026-01-04T20:00:00+00:00",
                "action": "ENTRY_LONG",
                "price": reference_price,
                "entry_type": "NORMAL_BREAKOUT",
                "quantity_units": 2,
            }
        ],
    }


def test_provenance_locked_bundle_can_prove_exact_sh24_fixture_parity():
    bundle = parse_parity_evidence_bundle(_bundle())
    report = evaluate_v24_evidence(bundle, _params())

    assert bundle.source == "TRADINGVIEW_EXPORT"
    assert bundle.source_revision == "sha256:fixture-v24-001"
    assert report.exact is True
    assert report.exact_match_count == 1


def test_reference_difference_remains_explicit_in_evidence_report():
    bundle = parse_parity_evidence_bundle(_bundle(reference_price=103.25))
    report = evaluate_v24_evidence(bundle, _params())

    assert report.exact is False
    assert {mismatch.kind for mismatch in report.mismatches} == {"PRICE_MISMATCH"}


def test_bundle_rejects_wrong_model_instead_of_crossing_books():
    bundle = parse_parity_evidence_bundle(_bundle(model_id="PAPER_SHADOW_V25"))

    with pytest.raises(ValueError, match="not SH24 CONTROL"):
        evaluate_v24_evidence(bundle, _params())


def test_bundle_requires_timezone_aware_strictly_ordered_bars():
    payload = _bundle()
    payload["bars"][1]["time"] = payload["bars"][0]["time"]

    with pytest.raises(ValueError, match="strictly chronological"):
        parse_parity_evidence_bundle(payload)


def test_bundle_requires_provenance_revision():
    payload = _bundle()
    payload["source_revision"] = ""

    with pytest.raises(ValueError, match="source_revision is required"):
        parse_parity_evidence_bundle(payload)
