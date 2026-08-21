"""Premium, readable HTML rendering for Daily Alpha research packets."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

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


@dataclass(frozen=True)
class _FlowRow:
    symbol: str
    option_type: str
    contract: str
    volume: int
    open_interest: int
    volume_oi_ratio: float
    bid: float
    ask: float
    classification: str


class NewsletterRenderer:
    """Render an institutional-grade publication without text compression or clipping."""

    def render(self, packet: DailyResearchPacket) -> RenderedNewsletter:
        sections: list[str] = []
        content: list[str] = []

        if packet.smart_money is not None and (
            packet.smart_money.congressional or packet.smart_money.institutional
        ):
            sections.append("SMART_MONEY")
            content.append(self._smart_money_section(packet.smart_money))

        if not packet.candidates:
            content.append(
                '<section class="report-section empty-state">'
                "<h2>No publishable candidates</h2>"
                "<p>The research engine produced no eligible records for this run.</p>"
                "</section>"
            )

        sections.append("UNUSUAL_OPTIONS_ACTIVITY")
        content.append(self._unusual_options_section(packet.candidates))

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
        candidates = packet.candidates
        option_count = sum(candidate.instrument.value == "OPTION" for candidate in candidates)
        paper_count = counts[ResearchDisposition.PAPER_CANDIDATE.value]
        watch_count = counts[ResearchDisposition.WATCHLIST.value]
        data_error_count = counts[ResearchDisposition.DATA_ERROR.value]
        actionable = tuple(
            candidate
            for candidate in candidates
            if candidate.disposition
            not in {ResearchDisposition.NO_TRADE, ResearchDisposition.DATA_ERROR}
        )
        focus = " · ".join(candidate.symbol for candidate in actionable[:4])
        if not focus:
            focus = "No validated setups"
        posture = "SELECTIVE / EVIDENCE-FIRST" if candidates else "WAIT / DATA REVIEW"
        return f"""
<section class="executive-dashboard" aria-label="Executive market dashboard">
  <div class="dashboard-eyebrow">EXECUTIVE SIGNAL BOARD</div>
  <div class="dashboard-headline">{escape(posture)}</div>
  <div class="dashboard-focus"><strong>Primary focus:</strong> {escape(focus)}</div>
  <table class="metric-table" role="presentation">
    <tbody>
      <tr>
        <td><span class="metric-label">Market regime</span><span class="metric-value">{escape(packet.market_regime)}</span></td>
        <td><span class="metric-label">Paper candidates</span><span class="metric-value">{paper_count}</span></td>
      </tr>
      <tr>
        <td><span class="metric-label">Watchlist</span><span class="metric-value">{watch_count}</span></td>
        <td><span class="metric-label">Qualified options / data flags</span><span class="metric-value">{option_count} / {data_error_count}</span></td>
      </tr>
    </tbody>
  </table>
</section>"""

    @staticmethod
    def _smart_money_section(snapshot: SmartMoneySnapshot) -> str:
        congress = "".join(
            NewsletterRenderer._smart_money_card(
                eyebrow=f"Congressional Rank #{item.rank}",
                symbol=item.symbol,
                score=item.score,
                primary=f"{item.unique_politicians} politicians · {item.purchase_count} purchases",
                secondary=f"Latest transaction {item.latest_transaction_date}",
            )
            for item in snapshot.congressional
        )
        institutions = "".join(
            NewsletterRenderer._smart_money_card(
                eyebrow=f"Institutional Rank #{item.rank}",
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
        return (
            '<section class="report-section smart-money">'
            '<div class="section-kicker">CAPITAL POSITIONING</div>'
            "<h2>Smart Money Accumulation</h2>"
            '<p class="section-note">Confirmation and rotation intelligence only. '
            "Congressional disclosures may lag transaction dates; 13F holdings are "
            "quarter-end snapshots and are not trade-timing signals.</p>"
            '<div class="card-grid">'
            f"{congress}{institutions}"
            "</div></section>"
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
    def _option_side(candidate: ResearchCandidate) -> str:
        contract = f" {candidate.option_contract or ''} ".upper()
        if " CALL " in contract:
            return "CALL"
        if " PUT " in contract:
            return "PUT"
        return "UNKNOWN"

    @staticmethod
    def _flow_records(candidates: tuple[ResearchCandidate, ...]) -> tuple[_FlowRow, ...]:
        rows: list[_FlowRow] = []
        for candidate in candidates:
            if candidate.option_flow_evidence:
                rows.extend(
                    _FlowRow(
                        symbol=candidate.symbol,
                        option_type=item.option_type,
                        contract=item.contract,
                        volume=item.volume,
                        open_interest=item.open_interest,
                        volume_oi_ratio=item.volume_oi_ratio,
                        bid=item.bid,
                        ask=item.ask,
                        classification=item.classification,
                    )
                    for item in candidate.option_flow_evidence
                )
                continue
            if (
                candidate.flow_classification == "UNUSUAL_CONFIRMATION"
                and candidate.option_volume_oi_ratio is not None
                and candidate.option_bid is not None
                and candidate.option_ask is not None
            ):
                rows.append(
                    _FlowRow(
                        symbol=candidate.symbol,
                        option_type=NewsletterRenderer._option_side(candidate),
                        contract=candidate.option_contract or "Contract unavailable",
                        volume=candidate.option_volume,
                        open_interest=candidate.option_open_interest,
                        volume_oi_ratio=candidate.option_volume_oi_ratio,
                        bid=candidate.option_bid,
                        ask=candidate.option_ask,
                        classification=candidate.flow_classification,
                    )
                )
        return tuple(rows)

    @staticmethod
    def _flow_cards(rows: tuple[_FlowRow, ...]) -> str:
        return "".join(
            '<article class="flow-card">'
            '<div class="flow-card-top">'
            f'<span class="symbol-chip">{escape(item.symbol)}</span>'
            f'<span class="side-chip">{escape(item.option_type)}</span>'
            "</div>"
            f'<div class="flow-contract">{escape(item.contract)}</div>'
            '<div class="flow-stats">'
            f'<span><b>{item.volume:,}</b><small>Volume</small></span>'
            f'<span><b>{item.open_interest:,}</b><small>Open interest</small></span>'
            f'<span><b>{item.volume_oi_ratio:.2f}x</b><small>Volume / OI</small></span>'
            f'<span><b>{item.bid:.2f} / {item.ask:.2f}</b><small>Bid / Ask</small></span>'
            "</div>"
            f'<div class="flow-classification">{escape(item.classification)}</div>'
            "</article>"
            for item in rows
        )

    @staticmethod
    def _flow_group(
        heading: str,
        rows: tuple[_FlowRow, ...],
        *,
        empty_message: str,
    ) -> str:
        if not rows:
            return (
                '<div class="flow-group">'
                f"<h3>{escape(heading)}</h3>"
                f'<p class="section-note">{escape(empty_message)}</p>'
                "</div>"
            )
        return (
            '<div class="flow-group">'
            f"<h3>{escape(heading)}</h3>"
            f'<div class="card-grid">{NewsletterRenderer._flow_cards(rows)}</div>'
            "</div>"
        )

    @staticmethod
    def _unusual_options_section(
        candidates: tuple[ResearchCandidate, ...],
    ) -> str:
        unusual = NewsletterRenderer._flow_records(candidates)
        flow_observed = any(
            item.option_flow_evidence or item.flow_classification is not None
            for item in candidates
        )

        if unusual:
            calls = tuple(item for item in unusual if item.option_type == "CALL")
            puts = tuple(item for item in unusual if item.option_type == "PUT")
            unknown = tuple(
                item for item in unusual if item.option_type not in {"CALL", "PUT"}
            )
            body = NewsletterRenderer._flow_group(
                "Unusual CALL Activity",
                calls,
                empty_message=(
                    "No shortlisted CALL contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
            body += NewsletterRenderer._flow_group(
                "Unusual PUT Activity",
                puts,
                empty_message=(
                    "No shortlisted PUT contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
            if unknown:
                body += NewsletterRenderer._flow_group(
                    "Unclassified Option-Side Activity",
                    unknown,
                    empty_message="",
                )
        elif flow_observed:
            body = NewsletterRenderer._flow_group(
                "Unusual CALL Activity",
                (),
                empty_message=(
                    "No shortlisted CALL contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
            body += NewsletterRenderer._flow_group(
                "Unusual PUT Activity",
                (),
                empty_message=(
                    "No shortlisted PUT contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
        else:
            body = (
                '<div class="data-warning"><strong>ORATS flow data unavailable.</strong> '
                "No unusual-options conclusion is reported for this run.</div>"
            )

        return (
            '<section class="report-section unusual-options">'
            '<div class="section-kicker">DERIVATIVES INTELLIGENCE</div>'
            "<h2>Unusual Options Activity — Calls &amp; Puts</h2>"
            '<p class="section-note">Confirmation evidence only; options flow cannot '
            "authorize a trade by itself. CALL and PUT identify the contract side, not "
            "whether the observed volume was buyer- or seller-initiated.</p>"
            f"{body}</section>"
        )

    @staticmethod
    def _candidate_section(
        disposition: ResearchDisposition,
        candidates: tuple[ResearchCandidate, ...],
    ) -> str:
        cards = "".join(
            NewsletterRenderer._candidate_card(candidate) for candidate in candidates
        )
        heading = disposition.value.replace("_", " ").title()
        kicker = {
            ResearchDisposition.PAPER_CANDIDATE: "ACTIONABLE PAPER RESEARCH",
            ResearchDisposition.WATCHLIST: "SETUP DEVELOPMENT",
            ResearchDisposition.NO_TRADE: "RISK DISCIPLINE",
            ResearchDisposition.DATA_ERROR: "DATA EXCEPTIONS",
        }[disposition]
        return (
            '<section class="report-section candidate-section">'
            f'<div class="section-kicker">{escape(kicker)}</div>'
            f"<h2>{escape(heading)}</h2>"
            f'<div class="candidate-stack">{cards}</div>'
            "</section>"
        )

    @staticmethod
    def _candidate_card(candidate: ResearchCandidate) -> str:
        reasons = " · ".join(candidate.reasons)
        contract = (
            f'<div class="candidate-contract">{escape(candidate.option_contract)}</div>'
            if candidate.option_contract
            else ""
        )
        risk = f"{candidate.risk_status} / {candidate.data_status}"
        planned_risk = (
            f"{candidate.planned_loss_nav:.2%} planned NAV risk"
            if candidate.planned_loss_nav is not None
            else "Risk not sized in research packet"
        )
        move = (
            f"{candidate.expected_move_pct:.1%} expected move"
            if candidate.expected_move_pct is not None
            else "Expected move unavailable"
        )
        return f"""
<article class="candidate-card">
  <div class="candidate-topline">
    <div>
      <span class="symbol-chip">{escape(candidate.symbol)}</span>
      <span class="signal-chip">{escape(candidate.signal_label)}</span>
    </div>
    <span class="risk-chip">{escape(risk)}</span>
  </div>
  <div class="candidate-title">{escape(candidate.sector)}</div>
  <div class="candidate-instrument"><strong>{escape(candidate.instrument.value)}</strong>{contract}</div>
  <div class="candidate-thesis">{escape(candidate.thesis)}</div>
  <div class="candidate-evidence"><strong>Evidence:</strong> {escape(reasons)}</div>
  <table class="candidate-metrics" role="presentation"><tbody><tr>
    <td><span>Risk frame</span><strong>{escape(planned_risk)}</strong></td>
    <td><span>Volatility context</span><strong>{escape(move)}</strong></td>
  </tr></tbody></table>
</article>"""

    @staticmethod
    def _document(packet: DailyResearchPacket, content: str) -> str:
        disclosures = "".join(f"<li>{escape(item)}</li>" for item in packet.disclosures)
        dashboard = NewsletterRenderer._dashboard(packet)
        body = content or (
            '<section class="report-section empty-state"><h2>No publishable candidates</h2>'
            "<p>The research engine produced no eligible records for this run.</p></section>"
        )
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{RESEARCH_PRODUCT} — {escape(packet.report_date)}</title>
<style>
@page {{ size: Letter; margin: 0.48in; }}
* {{ box-sizing: border-box; }}
html {{ background: #eef1f5; }}
body {{ margin: 0; color: #172033; background: #f7f8fa; font: 12pt/1.45 Arial, Helvetica, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
header {{ background: #0b1733; color: #ffffff; border-top: 5px solid #caa85e; padding: 26px 28px 24px; margin-bottom: 22px; }}
h1 {{ margin: 2px 0 0; font: 700 27pt/1.08 Georgia, 'Times New Roman', serif; letter-spacing: -0.02em; }}
h2 {{ margin: 2px 0 10px; font: 700 18pt/1.15 Georgia, 'Times New Roman', serif; color: #13294b; }}
h3 {{ margin: 18px 0 9px; font-size: 12.5pt; color: #13294b; }}
p {{ margin-top: 0; }}
main {{ padding: 0 6px; }}
.brand-kicker {{ font-size: 9pt; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: #d8bd7a; }}
.brand-line {{ margin-top: 8px; font-size: 10.5pt; color: #dce3ef; }}
.company-line {{ margin-top: 2px; font-size: 9.5pt; color: #aebbd0; }}
.meta {{ margin-top: 11px; font-size: 9.7pt; color: #c5cfdd; overflow-wrap: break-word; word-break: normal; }}
.executive-dashboard {{ margin-top: 22px; padding: 18px; background: #ffffff; color: #172033; border: 1px solid #d8dde6; border-top: 4px solid #caa85e; box-shadow: 0 8px 22px rgba(3, 15, 39, 0.10); }}
.dashboard-eyebrow, .section-kicker {{ font-size: 9pt; font-weight: 800; letter-spacing: 0.13em; color: #967326; text-transform: uppercase; }}
.dashboard-headline {{ margin-top: 3px; font: 700 18pt/1.15 Georgia, 'Times New Roman', serif; color: #0b1733; }}
.dashboard-focus {{ margin: 7px 0 13px; font-size: 10.5pt; color: #4a586c; overflow-wrap: break-word; word-break: normal; }}
.metric-table, .candidate-metrics {{ width: 100%; border-collapse: separate; border-spacing: 8px; table-layout: fixed; }}
.metric-table td {{ width: 50%; padding: 11px 12px; background: #f3f5f8; border: 1px solid #e0e5ec; vertical-align: top; }}
.metric-label {{ display: block; margin-bottom: 3px; font-size: 9pt; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: #69778a; }}
.metric-value {{ display: block; font-size: 12pt; font-weight: 800; color: #13294b; overflow-wrap: break-word; word-break: normal; }}
.report-section {{ margin: 0 0 28px; padding: 22px; background: #ffffff; border: 1px solid #dfe4eb; box-shadow: 0 5px 16px rgba(10, 29, 58, 0.05); break-inside: auto; page-break-inside: auto; }}
.section-note {{ margin: 0 0 14px; font-size: 10pt; color: #5d6a7c; overflow-wrap: break-word; word-break: normal; }}
.card-grid {{ display: flex; flex-wrap: wrap; gap: 12px; }}
.mini-card, .flow-card {{ flex: 1 1 260px; min-width: 0; padding: 15px; background: #f8f9fb; border: 1px solid #dfe4eb; border-top: 3px solid #caa85e; break-inside: avoid-page; page-break-inside: avoid; }}
.mini-eyebrow {{ font-size: 9pt; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #7a6740; }}
.mini-title {{ margin-top: 4px; font: 700 17pt/1.1 Georgia, 'Times New Roman', serif; color: #13294b; }}
.mini-score {{ margin-top: 4px; font-size: 9.5pt; font-weight: 700; color: #967326; }}
.mini-primary {{ margin-top: 10px; font-size: 10pt; color: #27364b; overflow-wrap: break-word; word-break: normal; }}
.mini-secondary {{ margin-top: 4px; font-size: 9pt; color: #6a7686; overflow-wrap: break-word; word-break: normal; }}
.flow-group + .flow-group {{ margin-top: 22px; }}
.flow-card-top, .candidate-topline {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-wrap: wrap; }}
.symbol-chip, .signal-chip, .side-chip, .risk-chip {{ display: inline-block; padding: 4px 8px; border-radius: 999px; font-size: 9pt; font-weight: 800; letter-spacing: 0.03em; vertical-align: middle; overflow-wrap: normal; word-break: normal; }}
.symbol-chip {{ background: #13294b; color: #ffffff; }}
.signal-chip {{ margin-left: 5px; background: #eee6d4; color: #765b1e; }}
.side-chip {{ background: #e8edf5; color: #273b5c; }}
.risk-chip {{ background: #edf1f6; color: #46566d; }}
.flow-contract {{ margin-top: 11px; font-size: 10.5pt; font-weight: 700; color: #23344d; overflow-wrap: break-word; word-break: normal; }}
.flow-stats {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }}
.flow-stats span {{ flex: 1 1 105px; min-width: 0; padding: 8px; background: #ffffff; border: 1px solid #e4e8ee; }}
.flow-stats b, .flow-stats small {{ display: block; }}
.flow-stats b {{ font-size: 10pt; color: #13294b; overflow-wrap: break-word; word-break: normal; }}
.flow-stats small {{ margin-top: 2px; font-size: 9pt; color: #748093; }}
.flow-classification {{ margin-top: 9px; font-size: 9pt; font-weight: 700; color: #765b1e; overflow-wrap: break-word; word-break: normal; }}
.data-warning {{ padding: 13px 15px; background: #fff8e8; border: 1px solid #ecdcae; font-size: 10pt; color: #66501d; overflow-wrap: break-word; word-break: normal; }}
.candidate-stack {{ display: block; }}
.candidate-card {{ margin: 0 0 14px; padding: 17px 18px; background: #fbfcfd; border: 1px solid #dce2ea; border-left: 4px solid #13294b; break-inside: avoid-page; page-break-inside: avoid; }}
.candidate-card:last-child {{ margin-bottom: 0; }}
.candidate-title {{ margin-top: 11px; font-size: 9pt; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: #7d8897; overflow-wrap: break-word; word-break: normal; }}
.candidate-instrument {{ margin-top: 4px; font-size: 10.5pt; color: #26374e; overflow-wrap: break-word; word-break: normal; }}
.candidate-contract {{ display: inline; margin-left: 7px; font-size: 9pt; color: #667488; }}
.candidate-thesis {{ margin-top: 10px; font-size: 11pt; color: #182940; overflow-wrap: break-word; word-break: normal; hyphens: auto; }}
.candidate-evidence {{ margin-top: 8px; padding-top: 8px; border-top: 1px solid #e6eaf0; font-size: 9.4pt; color: #596779; overflow-wrap: break-word; word-break: normal; hyphens: auto; }}
.candidate-metrics {{ margin-top: 10px; border-spacing: 0; }}
.candidate-metrics td {{ width: 50%; padding: 8px 10px; background: #f2f4f7; border-right: 6px solid #fbfcfd; vertical-align: top; }}
.candidate-metrics td:last-child {{ border-right: 0; }}
.candidate-metrics span, .candidate-metrics strong {{ display: block; }}
.candidate-metrics span {{ font-size: 9pt; text-transform: uppercase; letter-spacing: 0.06em; color: #788496; }}
.candidate-metrics strong {{ margin-top: 2px; font-size: 9.2pt; color: #26374e; overflow-wrap: break-word; word-break: normal; }}
.classification-overview {{ border-top: 4px solid #caa85e; }}
.classification-group {{ margin-top: 18px; break-inside: auto; page-break-inside: auto; }}
.table-wrap {{ width: 100%; margin-bottom: 12px; overflow: visible; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{ padding: 8px 9px; text-align: left; vertical-align: top; overflow-wrap: break-word; word-break: normal; hyphens: auto; }}
th {{ background: #13294b; color: #ffffff; border: 1px solid #13294b; font-size: 9pt; letter-spacing: 0.02em; }}
td {{ background: #ffffff; border: 1px solid #dce2ea; font-size: 10.5pt; color: #26374e; }}
.classification-overview th:first-child, .classification-overview td:first-child {{ width: 15%; }}
.classification-overview th:nth-child(2), .classification-overview td:nth-child(2) {{ width: 23%; }}
.classification-overview th:nth-child(3), .classification-overview td:nth-child(3) {{ width: 62%; }}
small {{ font-size: 9pt; color: #607084; }}
.empty-state {{ text-align: center; padding: 32px; }}
footer {{ margin: 28px 6px 0; padding: 16px 4px 4px; border-top: 1px solid #cfd6df; font-size: 9pt; color: #667488; }}
.footer-brand {{ margin-bottom: 10px; color: #344256; }}
footer li {{ margin-bottom: 4px; overflow-wrap: break-word; word-break: normal; }}
@media screen and (max-width: 720px) {{
  body {{ font-size: 11pt; }}
  header {{ padding: 20px 16px; }}
  main {{ padding: 0; }}
  .report-section {{ padding: 16px; }}
  .metric-table td, .candidate-metrics td {{ display: block; width: 100%; border-right: 0; margin-bottom: 6px; }}
  .mini-card, .flow-card {{ flex-basis: 100%; }}
  table {{ table-layout: fixed; }}
}}
</style>
</head>
<body>
<header>
<div class="brand-kicker">{RESEARCH_PRODUCT}</div>
<h1>{escape(NEWSLETTER_TITLE)}</h1>
<div class="brand-line">Quantitative Intelligence by <strong>{INSTITUTIONAL_BRAND}</strong></div>
<div class="company-line">A {PARENT_COMPANY} Company</div>
<div class="meta">{escape(packet.report_date)} · Run {escape(packet.run_id)} · Method {escape(packet.methodology_version)}</div>
{dashboard}
</header>
<main>{body}</main>
<footer>
<div class="footer-brand"><strong>{PRODUCT_BRAND}</strong> · Quantitative Intelligence by {INSTITUTIONAL_BRAND} · A {PARENT_COMPANY} Company</div>
<strong>Disclosures</strong><ul>{disclosures}</ul>
</footer>
</body>
</html>"""

    @staticmethod
    def _quality_checks(html: str, packet: DailyResearchPacket) -> tuple[str, ...]:
        warnings: list[str] = []
        if "height:" in html or "max-height:" in html:
            warnings.append("FIXED_HEIGHT_LAYOUT_DETECTED")
        if any(token in html for token in ("font-size: 7pt", "font-size: 7.5pt", "font-size: 8pt")):
            warnings.append("TEXT_TOO_SMALL")
        if "overflow-wrap: anywhere" in html or "word-break: break-all" in html:
            warnings.append("AGGRESSIVE_WORD_BREAKING_DETECTED")
        if "table-layout: auto" in html:
            warnings.append("UNBOUNDED_TABLE_LAYOUT_DETECTED")
        if "Unusual Options Activity" not in html:
            warnings.append("UNUSUAL_OPTIONS_SECTION_MISSING")
        if "EXECUTIVE SIGNAL BOARD" not in html:
            warnings.append("EXECUTIVE_DASHBOARD_MISSING")
        flow_observed = any(
            candidate.option_flow_evidence or candidate.flow_classification is not None
            for candidate in packet.candidates
        )
        if "Unusual CALL Activity" not in html and flow_observed:
            warnings.append("UNUSUAL_CALL_SECTION_MISSING")
        if "Unusual PUT Activity" not in html and flow_observed:
            warnings.append("UNUSUAL_PUT_SECTION_MISSING")
        if any(escape(candidate.symbol) not in html for candidate in packet.candidates):
            warnings.append("CANDIDATE_CONTENT_MISSING")
        if any(escape(item) not in html for item in packet.disclosures):
            warnings.append("DISCLOSURE_MISSING")
        if packet.smart_money is not None:
            smart_symbols = [item.symbol for item in packet.smart_money.congressional] + [
                item.symbol or item.cusip for item in packet.smart_money.institutional
            ]
            if any(escape(symbol) not in html for symbol in smart_symbols):
                warnings.append("SMART_MONEY_CONTENT_MISSING")
        return tuple(warnings)
