from datetime import UTC, datetime

from daily_alpha.models import InstrumentSelected
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
)
from daily_alpha.smart_money import (
    CongressionalAccumulation,
    InstitutionalAccumulation,
    build_smart_money_snapshot,
)


def candidate(symbol, disposition, instrument=InstrumentSelected.NONE):
    return ResearchCandidate(
        symbol=symbol,
        disposition=disposition,
        instrument=instrument,
        signal_label="ENTRY_WATCH",
        thesis="Trend < momentum & risk evidence.",
        reasons=("PINE_CONFIRMED", "RISK_APPROVED"),
        risk_status="APPROVED"
        if disposition == ResearchDisposition.PAPER_CANDIDATE
        else "WATCH",
        data_status="PASS",
        sector="TECHNOLOGY",
        option_contract="AAPL 2026-10-16 250C"
        if instrument == InstrumentSelected.OPTION
        else None,
    )


def smart_money_snapshot():
    congress = CongressionalAccumulation(
        rank=1,
        symbol="IBM",
        issuer="IBM",
        score=49.83,
        unique_politicians=2,
        purchase_count=2,
        estimated_purchase_value=50000.0,
        latest_transaction_date="2026-08-01",
        latest_disclosure_date="2026-08-12",
        average_disclosure_lag_days=11.0,
        politicians=("Member A", "Member B"),
    )
    institution = InstitutionalAccumulation(
        rank=1,
        symbol="MPWR",
        cusip="TICKER:MPWR",
        issuer="Monolithic Power Systems",
        score=100.0,
        managers_increasing=13,
        new_manager_positions=7,
        shares_added=100000.0,
        estimated_value_added=50000000.0,
        period_of_report="2026-06-30",
        top_managers=("Fund A", "Fund B"),
    )
    return build_smart_money_snapshot(
        generated_at=datetime(2026, 8, 17, 12, 30, tzinfo=UTC),
        congressional=(congress,),
        institutional=(institution,),
        coverage={"provider": "TEST"},
    )


def packet(*, include_smart_money=False):
    return DailyResearchPacket(
        "2026-08-17",
        "run-1",
        "daily-alpha-v2",
        "2026-08-17T12:35:00+00:00",
        "RISK_ON",
        (
            candidate(
                "AAPL", ResearchDisposition.PAPER_CANDIDATE, InstrumentSelected.OPTION
            ),
            candidate("MSFT", ResearchDisposition.WATCHLIST),
            candidate("TSLA", ResearchDisposition.NO_TRADE),
        ),
        smart_money=smart_money_snapshot() if include_smart_money else None,
    )


def test_renderer_includes_all_candidates_sections_and_disclosures():
    result = NewsletterRenderer().render(packet())
    assert result.candidate_count == 3
    assert result.sections == ("PAPER_CANDIDATE", "WATCHLIST", "NO_TRADE")
    assert all(symbol in result.html for symbol in ("AAPL", "MSFT", "TSLA"))
    assert "No live order execution is authorized." in result.html
    assert result.quality_passed is True


def test_renderer_includes_smart_money_confirmation_section():
    result = NewsletterRenderer().render(packet(include_smart_money=True))
    assert result.sections[0] == "SMART_MONEY"
    assert "Smart Money Accumulation" in result.html
    assert "Congressional accumulation" in result.html
    assert "Institutional accumulation" in result.html
    assert "IBM" in result.html
    assert "MPWR" in result.html
    assert "not trade-timing signals" in result.html
    assert result.quality_passed is True


def test_renderer_escapes_untrusted_candidate_text():
    result = NewsletterRenderer().render(packet())
    assert "Trend &lt; momentum &amp; risk evidence." in result.html
    assert "Trend < momentum" not in result.html


def test_layout_uses_readable_fonts_and_no_fixed_height_boxes():
    html = NewsletterRenderer().render(packet(include_smart_money=True)).html
    assert "font: 12pt" in html
    assert "font-size: 10.5pt" in html
    assert "height:" not in html
    assert "max-height:" not in html


def test_empty_packet_gets_explicit_no_candidate_message():
    empty = DailyResearchPacket(
        "2026-08-17",
        "run-empty",
        "v2",
        "2026-08-17T12:35:00+00:00",
        "NEUTRAL",
        (),
    )
    result = NewsletterRenderer().render(empty)
    assert "No publishable candidates" in result.html
    assert result.quality_passed is True
