from daily_alpha.models import InstrumentSelected
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
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


def packet():
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
    )


def test_renderer_includes_all_candidates_sections_and_disclosures():
    result = NewsletterRenderer().render(packet())
    assert result.candidate_count == 3
    assert result.sections == ("PAPER_CANDIDATE", "WATCHLIST", "NO_TRADE")
    assert all(symbol in result.html for symbol in ("AAPL", "MSFT", "TSLA"))
    assert "No live order execution is authorized." in result.html
    assert result.quality_passed is True


def test_renderer_escapes_untrusted_candidate_text():
    result = NewsletterRenderer().render(packet())
    assert "Trend &lt; momentum &amp; risk evidence." in result.html
    assert "Trend < momentum" not in result.html


def test_layout_uses_readable_fonts_and_no_fixed_height_boxes():
    html = NewsletterRenderer().render(packet()).html
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
