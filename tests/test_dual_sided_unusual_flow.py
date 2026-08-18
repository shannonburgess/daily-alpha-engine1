from datetime import UTC, datetime

from daily_alpha.models import InstrumentSelected, OptionCandidate
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.orats import OratsChain
from daily_alpha.research_report import (
    DailyResearchPacket,
    OptionFlowEvidence,
    ResearchCandidate,
    ResearchDisposition,
)
from daily_alpha.research_shortlist import build_research_shortlist
from daily_alpha.sources import OratsBatchResult
from daily_alpha.staging_reporting import _packet_from_shortlist

NOW = datetime(2026, 8, 18, 14, 30, tzinfo=UTC)


def _write_csv(path, signal):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Vol.\n"
        f"AAA,{signal},2026-08-18,Technology,Semiconductors,Up,Accelerating,Yes,100,1000000\n",
        encoding="utf-8",
    )
    return path


class _DualFlowSource:
    def fetch(self, symbols, *, as_of):
        assert symbols == ("AAA",)
        assert as_of == NOW
        call = OptionCandidate(
            symbol="AAA",
            expiration="2026-10-16",
            strike=105,
            option_type="CALL",
            dte=59,
            bid=5.0,
            ask=5.2,
            open_interest=500,
            volume=1500,
            delta=0.52,
        )
        put = OptionCandidate(
            symbol="AAA",
            expiration="2026-10-16",
            strike=95,
            option_type="PUT",
            dte=59,
            bid=4.0,
            ask=4.2,
            open_interest=600,
            volume=1800,
            delta=-0.48,
        )
        return OratsBatchResult(
            (OratsChain("AAA", (call, put), NOW, "delayed"),),
            (),
        )


def test_shortlist_preserves_unusual_call_and_put_independently(tmp_path):
    previous = _write_csv(tmp_path / "OVTLYR_2026-08-17.csv", "Hold")
    current = _write_csv(tmp_path / "OVTLYR_2026-08-18.csv", "Buy")

    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=_DualFlowSource(),
    )

    item = result.items[0]
    assert item.selected_option_type == "CALL"
    assert item.unusual_call_contract == "2026-10-16 CALL 105"
    assert item.unusual_call_volume_oi_ratio == 3.0
    assert item.unusual_put_contract == "2026-10-16 PUT 95"
    assert item.unusual_put_volume_oi_ratio == 3.0
    assert item.unusual_options_activity is True
    assert result.summary["unusual_call_company_count"] == 1
    assert result.summary["unusual_put_company_count"] == 1
    assert result.summary["trading_authorized"] is False


def test_staging_packet_carries_both_option_sides_from_one_company():
    packet = _packet_from_shortlist(
        [
            {
                "symbol": "AAA",
                "display_label": "EMERGING",
                "ovtlyr_status": "EMERGING",
                "classification_reason": "Momentum accelerating.",
                "score": 95.0,
                "sector": "Technology",
                "orats_status": "ENRICHED",
                "orats_reason": "QUALIFIED_OPTION_FOUND",
                "selected_expiration": "2026-10-16",
                "selected_option_type": "CALL",
                "selected_strike": 105,
                "selected_bid": 5.0,
                "selected_ask": 5.2,
                "selected_open_interest": 500,
                "selected_volume": 1500,
                "unusual_call_contract": "2026-10-16 CALL 105",
                "unusual_call_volume": 1500,
                "unusual_call_open_interest": 500,
                "unusual_call_volume_oi_ratio": 3.0,
                "unusual_call_bid": 5.0,
                "unusual_call_ask": 5.2,
                "unusual_put_contract": "2026-10-16 PUT 95",
                "unusual_put_volume": 1800,
                "unusual_put_open_interest": 600,
                "unusual_put_volume_oi_ratio": 3.0,
                "unusual_put_bid": 4.0,
                "unusual_put_ask": 4.2,
            }
        ],
        report_date="2026-08-18",
        run_id="dual-flow",
        generated_at=NOW.isoformat(),
    )

    candidate = packet.candidates[0]
    assert {item.option_type for item in candidate.option_flow_evidence} == {"CALL", "PUT"}
    html = NewsletterRenderer().render(packet).html
    assert "Unusual CALL Activity" in html
    assert "2026-10-16 CALL 105" in html
    assert "Unusual PUT Activity" in html
    assert "2026-10-16 PUT 95" in html


def test_newsletter_allows_same_company_in_both_flow_tables():
    candidate = ResearchCandidate(
        symbol="AAA",
        disposition=ResearchDisposition.WATCHLIST,
        instrument=InstrumentSelected.OPTION,
        signal_label="EMERGING",
        thesis="Dual-sided flow confirmation.",
        reasons=("ORATS_FLOW",),
        risk_status="WATCH",
        data_status="PASS",
        sector="Technology",
        option_contract="2026-10-16 CALL 105",
        option_flow_evidence=(
            OptionFlowEvidence(
                option_type="CALL",
                contract="2026-10-16 CALL 105",
                volume=1500,
                open_interest=500,
                volume_oi_ratio=3.0,
                bid=5.0,
                ask=5.2,
            ),
            OptionFlowEvidence(
                option_type="PUT",
                contract="2026-10-16 PUT 95",
                volume=1800,
                open_interest=600,
                volume_oi_ratio=3.0,
                bid=4.0,
                ask=4.2,
            ),
        ),
    )
    packet = DailyResearchPacket(
        report_date="2026-08-18",
        run_id="dual-flow-render",
        methodology_version="DAILY_ALPHA_V1_9_STAGING",
        generated_at=NOW.isoformat(),
        market_regime="RESEARCH_ONLY",
        candidates=(candidate,),
    )

    result = NewsletterRenderer().render(packet)
    assert result.quality_passed is True
    assert "2026-10-16 CALL 105" in result.html
    assert "2026-10-16 PUT 95" in result.html
    assert "buyer- or seller-initiated" in result.html
