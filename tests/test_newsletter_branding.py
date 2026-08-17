from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import DailyResearchPacket


def test_newsletter_uses_daily_alpha_brand_architecture():
    packet = DailyResearchPacket(
        report_date="2026-08-17",
        run_id="brand-test",
        methodology_version="daily-alpha-v2.4",
        generated_at="2026-08-17T12:00:00+00:00",
        market_regime="RESEARCH_ONLY",
        candidates=(),
    )

    result = NewsletterRenderer().render(packet)

    assert "Daily Alpha Research" in result.html
    assert "Daily Alpha &amp; Risk" in result.html
    assert "Convex Ridge Quantitative" in result.html
    assert "A Daily Alpha Labs Company" in result.html
    assert "Quantitative Intelligence by" in result.html
    assert result.quality_passed is True
