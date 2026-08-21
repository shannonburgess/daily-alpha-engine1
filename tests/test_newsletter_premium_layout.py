from daily_alpha.models import InstrumentSelected
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
)


def _packet() -> DailyResearchPacket:
    candidate = ResearchCandidate(
        symbol="PR",
        disposition=ResearchDisposition.WATCHLIST,
        instrument=InstrumentSelected.OPTION,
        signal_label="ACTIVE BUY CONTINUATION ENTRY WATCH",
        thesis=(
            "Persistent leadership remains intact after the original breakout while "
            "price remains inside the controlled no-chase envelope."
        ),
        reasons=(
            "ACTIVE_BUY_CONTINUATION",
            "LIQUIDITY_GATE_PASSED",
            "EARNINGS_RISK_CLEAR",
        ),
        risk_status="WATCH",
        data_status="PASS",
        sector="Energy — Exploration & Production",
        option_contract="2026-10-16 CALL 25",
        user_directed_option=True,
    )
    return DailyResearchPacket(
        report_date="2026-08-20",
        run_id="premium-layout-test",
        methodology_version="daily-alpha-v2.4",
        generated_at="2026-08-20T22:00:00+00:00",
        market_regime="SELECTIVE RISK-ON / ROTATION",
        candidates=(candidate,),
    )


def test_premium_newsletter_has_executive_dashboard_and_institutional_cards():
    html = NewsletterRenderer().render(_packet()).html

    assert "EXECUTIVE SIGNAL BOARD" in html
    assert "Primary focus:" in html
    assert "candidate-card" in html
    assert "USER-DIRECTED OPTIONS" in html
    assert "broker-chain" in html.lower()
    assert "CAPITAL POSITIONING" not in html  # no smart-money evidence in this fixture
    assert "#0b1733" in html
    assert "#caa85e" in html


def test_premium_newsletter_prevents_runoff_without_destroying_words():
    result = NewsletterRenderer().render(_packet())
    html = result.html

    assert result.quality_passed is True
    assert "overflow-wrap: anywhere" not in html
    assert "word-break: break-all" not in html
    assert "white-space: nowrap" not in html
    assert "table-layout: auto" not in html
    assert "table-layout: fixed" in html
    assert "overflow-wrap: break-word" in html
    assert "word-break: normal" in html
    assert "font-size: 8pt" not in html
    assert "font-size: 7pt" not in html


def test_classification_width_rules_are_scoped_and_do_not_distort_metric_tables():
    html = NewsletterRenderer().render(_packet()).html

    assert ".classification-overview th:first-child" in html
    assert ".classification-overview td:first-child" in html
    assert "th:first-child, td:first-child" not in html
    assert ".metric-table td { width: 50%" in html
