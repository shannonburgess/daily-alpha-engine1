from daily_alpha.models import InstrumentSelected
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
)


def _packet(candidate: ResearchCandidate) -> DailyResearchPacket:
    return DailyResearchPacket(
        report_date="2026-08-18",
        run_id="test-option-entry-plan",
        methodology_version="TEST",
        generated_at="2026-08-18T17:00:00+00:00",
        market_regime="RESEARCH_ONLY",
        candidates=(candidate,),
    )


def test_qualified_option_setup_includes_exact_contract_and_rule_based_entry_prices():
    candidate = ResearchCandidate(
        symbol="MU",
        disposition=ResearchDisposition.WATCHLIST,
        instrument=InstrumentSelected.OPTION,
        signal_label="ENTRY WATCH",
        thesis="Qualified option setup.",
        reasons=("ORATS=QUALIFIED_OPTION_FOUND",),
        risk_status="NOT_EVALUATED",
        data_status="PASS",
        sector="Technology",
        option_contract="2026-10-16 CALL 100.0",
        option_volume=125,
        option_open_interest=500,
        option_volume_oi_ratio=0.25,
        option_bid=2.00,
        option_ask=2.20,
    )

    rendered = NewsletterRenderer().render(_packet(candidate))

    assert rendered.quality_passed
    assert "OPTION_ENTRY_PLANS" in rendered.sections
    assert "Trade Setups — Option Entry Plan" in rendered.html
    assert "2026-10-16 CALL 100.0" in rendered.html
    assert "$2.00 / $2.20" in rendered.html
    assert "$2.10" in rendered.html  # midpoint target limit
    assert "$2.15" in rendered.html  # midpoint + 25% of spread
    assert "500 / 125" in rendered.html


def test_invalid_or_missing_option_quote_does_not_publish_entry_plan():
    candidate = ResearchCandidate(
        symbol="MU",
        disposition=ResearchDisposition.WATCHLIST,
        instrument=InstrumentSelected.OPTION,
        signal_label="ENTRY WATCH",
        thesis="Option identity exists but quote is invalid.",
        reasons=("ORATS=QUOTE_INVALID",),
        risk_status="NOT_EVALUATED",
        data_status="PASS",
        sector="Technology",
        option_contract="2026-10-16 CALL 100.0",
        option_bid=0.0,
        option_ask=2.20,
    )

    rendered = NewsletterRenderer().render(_packet(candidate))

    assert rendered.quality_passed
    assert "OPTION_ENTRY_PLANS" not in rendered.sections
    assert "Trade Setups — Option Entry Plan" not in rendered.html
