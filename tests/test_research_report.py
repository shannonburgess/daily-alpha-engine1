import pytest

from daily_alpha.models import InstrumentSelected
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
    data_error_candidate,
)


def option_candidate(symbol="AAPL"):
    return ResearchCandidate(
        symbol=symbol,
        disposition=ResearchDisposition.PAPER_CANDIDATE,
        instrument=InstrumentSelected.OPTION,
        signal_label="ENTRY_WATCH",
        thesis="Trend and momentum align with the approved research rules.",
        reasons=("PINE_ENTRY", "RISK_APPROVED", "ORATS_QUALITY_PASS"),
        risk_status="APPROVED",
        data_status="PASS",
        sector="TECHNOLOGY",
        option_contract="AAPL 2026-10-16 250C",
        planned_loss_nav=0.004,
        expected_move_pct=0.06,
        flow_classification="UNUSUAL_CONFIRMATION",
    )


def test_packet_is_versioned_reproducible_and_newsletter_ready():
    packet = DailyResearchPacket(
        report_date="2026-08-15",
        run_id="run-123",
        methodology_version="daily-alpha-v1",
        generated_at="2026-08-15T21:00:00+00:00",
        market_regime="RISK_ON",
        candidates=(option_candidate(),),
    )
    payload = packet.to_dict()
    assert payload["counts"]["PAPER_CANDIDATE"] == 1
    assert payload["candidates"][0]["instrument"] == "OPTION"
    assert len(payload["disclosures"]) == 2


def test_stale_orats_is_data_error_with_no_stock_fallback():
    candidate = data_error_candidate("MSFT", reason="ORATS_STALE", signal_label="LEADER")
    assert candidate.disposition == ResearchDisposition.DATA_ERROR
    assert candidate.instrument == InstrumentSelected.NONE


def test_flow_cannot_be_standalone_signal():
    with pytest.raises(ValueError, match="standalone"):
        ResearchCandidate(
            "SPY",
            ResearchDisposition.WATCHLIST,
            InstrumentSelected.NONE,
            "FLOW",
            "Flow only.",
            ("UNUSUAL_FLOW",),
            "NOT_EVALUATED",
            "PASS",
            standalone_flow_signal=True,
        )


def test_paper_candidate_must_pass_risk_and_data():
    with pytest.raises(ValueError, match="approved risk"):
        ResearchCandidate(
            "NVDA",
            ResearchDisposition.PAPER_CANDIDATE,
            InstrumentSelected.STOCK,
            "ENTRY_WATCH",
            "Momentum setup.",
            ("PINE_ENTRY",),
            "REJECTED",
            "PASS",
        )


def test_daily_packet_rejects_duplicate_symbols():
    with pytest.raises(ValueError, match="unique"):
        DailyResearchPacket(
            "2026-08-15",
            "run-123",
            "v1",
            "2026-08-15T21:00:00+00:00",
            "RISK_ON",
            (option_candidate(), option_candidate()),
        )
