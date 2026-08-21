"""Premium, readable HTML rendering for Daily Alpha research packets.

The renderer is stock-primary and visual-first. Automatic unusual-options-flow and
external derivatives-data sections are intentionally absent. A compact options
section appears only for explicitly user-directed OPTION candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .models import InstrumentSelected
from .research_report import DailyResearchPacket, ResearchCandidate, ResearchDisposition
from .smart_money import SmartMoneySnapshot

PARENT_COMPANY = "Daily Alpha Labs"
INSTITUTIONAL_BRAND = "Convex Ridge Quantitative"
PRODUCT_BRAND = "Daily Alpha"
RESEARCH_PRODUCT = "Daily Alpha Research"
NEWSLETTER_TITLE = "Daily Alpha & Risk"


@dataclass(frozen=True)
class RenderedNewsletter:
    html: str
    candidate_count: int
    sections: tuple[str, ...]
    quality_warnings: tuple[str, ...]

    @property
    def quality_passed(self) -> bool:
        return not self.quality_warnings


class NewsletterRenderer:
    """Render an institutional-grade, scan-first publication."""

    def render(self, packet: DailyResearchPacket) -> RenderedNewsletter:
        sections: list[str] = []
        content: list[str] = [self._dashboard(packet)]

        if packet.smart_money is not None and (
            packet.smart_money.congressional or packet.smart_money.institutional
        ):
            sections.append("SMART_MONEY")
            content.append(self._smart_money_section(packet.smart_money))

        user_options = tuple(
            candidate
            for candidate in packet.candidates
            if candidate.instrument == InstrumentSelected.OPTION
        )
        if user_options:
            sections.append("USER_DIRECTED_OPTIONS")
            content.append(self._user_directed_options_section(user_options))

        if not packet.candidates:
            content.append(
                '<section class="report-section empty-state">'
                "<h2>No publishable candidates</h2>"
                "<p>The research engine produced no eligible records for this run.</p>"
                "</section>"
            )

        for disposition in ResearchDisposition:
            candidates = tuple(
                candidate
                for candidate in packet.candidates
                if candidate.disposition == disposition
            )
            if not candidates:
                continue
            sections.append(disposition.value)
            content.append(self._candidate_section(disposition, candidates))

        html = self._document(packet, "".join(content))
        warnings = self._quality_checks(html, packet)
        return RenderedNewsletter(
            html=html,
            candidate_count=len(packet.candidates),
            sections=tuple(sections),
            quality_warnings=warnings,
        )

    @staticmethod
    def _dashboard(packet: DailyResearchPacket) -> str:
        counts = packet.counts
        paper_count = counts[ResearchDisposition.PAPER_CANDIDATE.value]
        watch_count = counts[ResearchDisposition.WATCHLIST.value]
        data_error_count = counts[ResearchDisposition.DATA_ERROR.value]
        user_option_count = sum(
            candidate.instrument == InstrumentSelected.OPTION
            for candidate in packet.candidates
        )
        actionable = tuple(
            candidate
            for candidate in packet.candidates
            if candidate.disposition
            not in {ResearchDisposition.NO_TRADE, ResearchDisposition.DATA_ERROR}
        )
        focus = " · ".join(candidate.symbol for candidate in actionable[:4])
        if not focus:
            focus = "No validated setups"
        posture = "SELECTIVE / EVIDENCE-FIRST" if packet.candidates else "WAIT / DATA REVIEW"
        return f"""
<section class="executive-dashboard" aria-label="Executive signal board">
  <div class="dashboard-eyebrow">EXECUTIVE SIGNAL BOARD</div>
  <div class="dashboard-headline">{escape(posture)}</div>
  <div class="dashboard-focus"><strong>Primary focus:</strong> {escape(focus)}</div>
  <table class="metric-table" role="presentation">
    <tbody>
      <tr>
        <td><span class="metric-label">Market regime</span><span class="metric-value">{escape(packet.market_regime)}</span></td>
        <td><span class="metric-label">PAPER candidates</span><span class="metric-value">{paper_count}</span></td>
      </tr>
      <tr>
        <td><span class="metric-label">Watchlist / data flags</span><span class="metric-value">{watch_count} / {data_error_count}</span></td>
        <td><span class="metric-label">User-directed options</span><span class="metric-value">{user_option_count}</span></td>
      </tr>
    </tbody>
  </table>
</section>"""

    @staticmethod
    def _smart_money_section(snapshot: SmartMoneySnapshot) -> str:
        congress_cards = "".join(
            NewsletterRenderer._smart_money_card(
                eyebrow=f"Rank #{item.rank}",
                symbol=item.symbol,
                score=item.score,
                primary=f"{item.unique_politicians} politicians · {item.purchase_count} purchases",
                secondary=f"Latest transaction {item.latest_transaction_date}",
            )
            for item in snapshot.congressional
        )
        institution_cards = "".join(
            NewsletterRenderer._smart_money_card(
                eyebrow=f"Rank #{item.rank}",
                symbol=item.symbol or item.cusip,
                score=item.score,
                primary=(
                    f"{item.managers_increasing} managers adding · "
                    f"{item.new_manager_positions} new positions"
                ),
                secondary=f"13F period {item.period_of_report}",
            )
            for item in snapshot.institutional
        )
        congress = (
            '<div class="smart-money-lane"><h3>Congressional accumulation — Top 5</h3>'
            f'<div class="card-grid">{congress_cards}</div></div>'
            if congress_cards
            else ""
        )
        institutions = (
            '<div class="smart-money-lane"><h3>Institutional accumulation — Top 5</h3>'
            f'<div class="card-grid">{institution_cards}</div></div>'
            if institution_cards
            else ""
        )
        return (
            '<section class="report-section smart-money">'
            '<div class="section-kicker">CAPITAL POSITIONING</div>'
            "<h2>Smart Money Accumulation</h2>"
            '<p class="section-note">Confirmation and rotation intelligence only. '
            "Congressional disclosures may lag transaction dates; 13F holdings are "
            "quarter-end snapshots and are not trade-timing signals.</p>"
            f"{congress}{institutions}</section>"
        )

    @staticmethod
    def _smart_money_card(
        *,
        eyebrow: str,
        symbol: str,
        score: float,
        primary: str,
        secondary: str,
    ) -> str:
        return (
            '<article class="mini-card">'
            f'<div class="mini-eyebrow">{escape(eyebrow)}</div>'
            f'<div class="mini-title">{escape(symbol)}</div>'
            f'<div class="mini-score">Score {score:.2f}</div>'
            f'<div class="mini-primary">{escape(primary)}</div>'
            f'<div class="mini-secondary">{escape(secondary)}</div>'
            "</article>"
        )

    @staticmethod
    def _user_directed_options_section(
        candidates: tuple[ResearchCandidate, ...],
    ) -> str:
        cards = "".join(
            '<article class="candidate-card option-card">'
            '<div class="candidate-topline">USER-DIRECTED · BROKER-CHAIN DATA</div>'
            f'<h3>{escape(candidate.symbol)}</h3>'
            f'<div class="contract-line">{escape(candidate.option_contract or "Contract required")}</div>'
            f'<p>{escape(candidate.thesis)}</p>'
            '<div class="status-chip">Explicit user authorization required</div>'
            "</article>"
            for candidate in candidates
        )
        return (
            '<section class="report-section user-directed-options">'
            '<div class="section-kicker">USER-DIRECTED OPTIONS</div>'
            "<h2>Explicitly Authorized Option Orders</h2>"
            '<p class="section-note">No automated option selection, flow feed, or option-chain '
            "vendor is used. Contract terms come from the broker chain and every BUY/SELL "
            "instruction requires explicit user direction.</p>"
            f'<div class="card-grid">{cards}</div></section>'
        )

    @staticmethod
    def _candidate_section(
        disposition: ResearchDisposition,
        candidates: tuple[ResearchCandidate, ...],
    ) -> str:
        title = {
            ResearchDisposition.PAPER_CANDIDATE: "PAPER Candidates",
            ResearchDisposition.WATCHLIST: "Entry / Re-entry Radar",
            ResearchDisposition.NO_TRADE: "Risk & Discipline — No Trade",
            ResearchDisposition.DATA_ERROR: "Data Error",
        }[disposition]
        kicker = {
            ResearchDisposition.PAPER_CANDIDATE: "MODEL VALIDATION",
            ResearchDisposition.WATCHLIST: "SETUP DEVELOPMENT",
            ResearchDisposition.NO_TRADE: "DISCIPLINE",
            ResearchDisposition.DATA_ERROR: "FAIL-CLOSED DATA CONTROL",
        }[disposition]
        cards = "".join(NewsletterRenderer._candidate_card(item) for item in candidates)
        return (
            f'<section class="report-section disposition-{disposition.value.lower()}">'
            f'<div class="section-kicker">{escape(kicker)}</div>'
            f"<h2>{escape(title)}</h2>"
            f'<div class="card-grid">{cards}</div></section>'
        )

    @staticmethod
    def _candidate_card(candidate: ResearchCandidate) -> str:
        reason_items = "".join(
            f"<li>{escape(reason)}</li>" for reason in candidate.reasons[:5]
        )
        instrument = candidate.instrument.value
        if candidate.instrument == InstrumentSelected.OPTION:
            instrument = "OPTION · USER-DIRECTED"
        contract = (
            f'<div class="contract-line">{escape(candidate.option_contract or "")}</div>'
            if candidate.option_contract
            else ""
        )
        planned = (
            f" · Planned loss {candidate.planned_loss_nav:.2%} NAV"
            if candidate.planned_loss_nav is not None
            else ""
        )
        return (
            '<article class="candidate-card">'
            f'<div class="candidate-topline">{escape(candidate.signal_label)} · {escape(candidate.sector)}</div>'
            f'<h3>{escape(candidate.symbol)}</h3>'
            f'<div class="instrument-chip">{escape(instrument)}</div>'
            f"{contract}"
            f'<p class="candidate-thesis">{escape(candidate.thesis)}</p>'
            f'<ul class="reason-list">{reason_items}</ul>'
            f'<div class="candidate-footer">Risk {escape(candidate.risk_status)} · Data {escape(candidate.data_status)}{escape(planned)}</div>'
            "</article>"
        )

    @staticmethod
    def _document(packet: DailyResearchPacket, content: str) -> str:
        disclosures = "".join(f"<li>{escape(item)}</li>" for item in packet.disclosures)
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(NEWSLETTER_TITLE)}</title>
<style>
@page {{ margin: 0.52in; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f5f3ee; color: #172033; font: 12pt Georgia, 'Times New Roman', serif; overflow-wrap: break-word; word-break: normal; }}
main {{ padding: 24px; }}
.masthead {{ background: #0b1733; color: #ffffff; padding: 22px 24px 18px; border-bottom: 4px solid #caa85e; }}
.masthead-kicker, .section-kicker, .dashboard-eyebrow, .candidate-topline, .mini-eyebrow, .metric-label {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; letter-spacing: .08em; text-transform: uppercase; }}
.masthead h1 {{ margin: 5px 0 4px; font-size: 25pt; font-weight: 700; }}
.masthead-sub {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; color: #e6e9ef; }}
.executive-dashboard {{ background: #ffffff; border: 1px solid #d8d5cd; border-top: 4px solid #caa85e; padding: 18px; margin-bottom: 18px; }}
.dashboard-eyebrow, .section-kicker {{ color: #8a6a2c; font-weight: 700; }}
.dashboard-headline {{ font-size: 21pt; color: #0b1733; margin: 5px 0; }}
.dashboard-focus {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; margin-bottom: 12px; }}
.metric-table {{ width: 100%; border-collapse: separate; border-spacing: 8px; table-layout: fixed; }}
.metric-table td {{ width: 50%; background: #f7f7f5; border: 1px solid #dfddd7; padding: 11px; vertical-align: top; overflow-wrap: break-word; word-break: normal; }}
.metric-label {{ display: block; color: #687083; margin-bottom: 5px; }}
.metric-value {{ display: block; color: #0b1733; font-family: Arial, Helvetica, sans-serif; font-weight: 700; }}
.report-section {{ background: #ffffff; border: 1px solid #ddd9d0; margin: 0 0 18px; padding: 18px; break-inside: avoid; }}
.report-section h2 {{ color: #0b1733; font-size: 19pt; margin: 4px 0 10px; }}
.report-section h3 {{ color: #0b1733; font-size: 14pt; margin: 4px 0 7px; }}
.section-note, .candidate-card p, .candidate-footer, .mini-primary, .mini-secondary {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; }}
.card-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
.candidate-card, .mini-card {{ border: 1px solid #dedbd4; border-top: 3px solid #0b1733; background: #fbfbfa; padding: 13px; break-inside: avoid; overflow-wrap: break-word; word-break: normal; }}
.option-card {{ border-top-color: #caa85e; }}
.candidate-topline, .mini-eyebrow {{ color: #687083; }}
.instrument-chip, .status-chip {{ display: inline-block; font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; padding: 4px 7px; border: 1px solid #c9c5bb; background: #f1efe9; color: #0b1733; margin-bottom: 7px; }}
.contract-line {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; font-weight: 700; color: #8a6a2c; margin: 3px 0 6px; }}
.reason-list {{ margin: 8px 0 8px 18px; padding: 0; font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; }}
.candidate-footer {{ border-top: 1px solid #e1ded7; padding-top: 7px; color: #555f72; }}
.smart-money-lane {{ margin-top: 14px; }}
.mini-title {{ font-size: 16pt; color: #0b1733; font-weight: 700; }}
.mini-score {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; color: #8a6a2c; font-weight: 700; }}
.disclosures {{ background: #0b1733; color: #ffffff; padding: 16px 22px; font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; }}
.disclosures h2 {{ margin: 0 0 7px; font-family: Georgia, 'Times New Roman', serif; }}
.classification-overview table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
.classification-overview th, .classification-overview td {{ border-bottom: 1px solid #e1ded7; padding: 7px; text-align: left; vertical-align: top; font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; overflow-wrap: break-word; word-break: normal; }}
.classification-overview th:first-child, .classification-overview td:first-child {{ width: 16%; }}
.classification-overview th:nth-child(2), .classification-overview td:nth-child(2) {{ width: 24%; }}
.classification-overview th:nth-child(3), .classification-overview td:nth-child(3) {{ width: 60%; }}
@media (max-width: 760px) {{ .card-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header class="masthead">
  <div class="masthead-kicker">{escape(RESEARCH_PRODUCT)}</div>
  <h1>{escape(NEWSLETTER_TITLE)}</h1>
  <div class="masthead-sub">Quantitative Intelligence by {escape(INSTITUTIONAL_BRAND)} · A {escape(PARENT_COMPANY)} Company</div>
  <div class="masthead-sub">{escape(packet.report_date)} · {escape(packet.methodology_version)} · Run {escape(packet.run_id)}</div>
</header>
<main>{content}</main>
<footer class="disclosures"><h2>Methodology & Disclosures</h2><ul>{disclosures}</ul></footer>
</body>
</html>"""

    @staticmethod
    def _quality_checks(
        html: str,
        packet: DailyResearchPacket,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        forbidden = (
            "overflow-wrap: anywhere",
            "word-break: break-all",
            "white-space: nowrap",
            "font-size: 8pt",
            "font-size: 7pt",
        )
        for marker in forbidden:
            if marker in html:
                warnings.append(f"FORBIDDEN_LAYOUT_RULE:{marker}")
        for candidate in packet.candidates:
            if candidate.symbol not in html:
                warnings.append(f"CANDIDATE_MISSING:{candidate.symbol}")
            if candidate.instrument == InstrumentSelected.OPTION and not candidate.user_directed_option:
                warnings.append(f"UNAUTHORIZED_OPTION_CANDIDATE:{candidate.symbol}")
        return tuple(warnings)
