from daily_alpha.models import InstrumentSelected
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
)


def _flow_candidate(symbol: str, option_type: str, ratio: float) -> ResearchCandidate:
    return ResearchCandidate(
        symbol=symbol,
        disposition=ResearchDisposition.WATCHLIST,
        instrument=InstrumentSelected.OPTION,
        signal_label="ENTRY_WATCH",
        thesis="ORATS flow confirmation only.",
        reasons=("ORATS_FLOW",),
        risk_status="WATCH",
        data_status="PASS",
        sector="Technology",
        option_contract=f"2026-10-16 {option_type} 250",
        flow_classification="UNUSUAL_CONFIRMATION",
        option_volume=1200,
        option_open_interest=int(1200 / ratio),
        option_volume_oi_ratio=ratio,
        option_bid=4.8,
        option_ask=5.0,
    )


def test_newsletter_separates_unusual_call_and_put_activity_by_company():
    packet = DailyResearchPacket(
        report_date="2026-08-18",
        run_id="flow-test",
        methodology_version="DAILY_ALPHA_V1_9_STAGING",
        generated_at="2026-08-18T14:30:00+00:00",
        market_regime="RESEARCH_ONLY",
        candidates=(
            _flow_candidate("AAPL", "CALL", 2.0),
            _flow_candidate("NVDA", "PUT", 1.5),
        ),
    )

    result = NewsletterRenderer().render(packet)

    assert result.quality_passed is True
    assert "Unusual Options Activity — Calls &amp; Puts" in result.html
    assert "Unusual CALL Activity" in result.html
    assert "Unusual PUT Activity" in result.html
    assert "AAPL" in result.html
    assert "2026-10-16 CALL 250" in result.html
    assert "NVDA" in result.html
    assert "2026-10-16 PUT 250" in result.html
    assert "buyer- or seller-initiated" in result.html
