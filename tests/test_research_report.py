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
        signal_label="USER_DIRECTED_OPTION",
        thesis="User explicitly directed this option order using broker-chain data.",
        reasons=("USER_AUTHORIZED", "BROKER_CHAIN_CONTRACT", "RISK_APPROVED"),
        risk_status="APPROVED",
        data_status="PASS",
        sector="TECHNOLOGY",
        option_contract="AAPL 2026-10-16 250C",
        planned_loss_nav=0.004,
        expected_move_pct=0.06,
        user_directed_option=True,
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
    assert payload["candidates"][0]["user_directed_option"] is True
    assert len(payload["disclosures"]) == 3


def test_missing_required_market_data_is_fail_closed():
    candidate = data_error_candidate(
        "MSFT",
        reason="CURRENT_MARKET_DATA_STALE",
        signal_label="LEADER",
    )
    assert candidate.disposition == ResearchDisposition.DATA_ERROR
    assert candidate.instrument == InstrumentSelected.NONE


def test_option_candidate_requires_explicit_user_direction():
    with pytest.raises(ValueError, match="explicit user-directed"):
        ResearchCandidate(
            "SPY",
            ResearchDisposition.WATCHLIST,
            InstrumentSelected.OPTION,
            "OPTION_WATCH",
            "Option contract supplied without user authorization.",
            ("BROKER_CHAIN_CONTRACT",),
            "WATCH",
            "PASS",
            option_contract="SPY 2026-10-16 700C",
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
