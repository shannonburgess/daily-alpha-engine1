"""Readable, deterministic HTML rendering for Daily Alpha research packets."""

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


class NewsletterRenderer:
    """Render fluid pages; never shrink text to force content into boxes."""

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
                "<section><h2>No publishable candidates</h2>"
                "<p>The research engine produced no eligible records for this run.</p></section>"
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
    def _smart_money_section(snapshot: SmartMoneySnapshot) -> str:
        congress_rows = "".join(
            "<tr>"
            f"<td>{item.rank}</td>"
            f"<td><strong>{escape(item.symbol)}</strong></td>"
            f"<td>{item.score:.2f}</td>"
            f"<td>{item.unique_politicians}</td>"
            f"<td>{item.purchase_count}</td>"
            f"<td>{escape(item.latest_transaction_date)}</td>"
            "</tr>"
            for item in snapshot.congressional
        )
        institution_rows = "".join(
            "<tr>"
            f"<td>{item.rank}</td>"
            f"<td><strong>{escape(item.symbol or item.cusip)}</strong></td>"
            f"<td>{item.score:.2f}</td>"
            f"<td>{item.managers_increasing}</td>"
            f"<td>{item.new_manager_positions}</td>"
            f"<td>{escape(item.period_of_report)}</td>"
            "</tr>"
            for item in snapshot.institutional
        )
        congress_table = (
            '<h3>Congressional accumulation — Top 5</h3>'
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Rank</th><th>Symbol</th><th>Score</th><th>Politicians</th>"
            "<th>Purchases</th><th>Latest transaction</th>"
            f"</tr></thead><tbody>{congress_rows}</tbody></table></div>"
            if congress_rows
            else ""
        )
        institution_table = (
            '<h3>Institutional accumulation — Top 5</h3>'
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Rank</th><th>Symbol</th><th>Score</th><th>Managers adding</th>"
            "<th>New positions</th><th>13F period</th>"
            f"</tr></thead><tbody>{institution_rows}</tbody></table></div>"
            if institution_rows
            else ""
        )
        return (
            '<section class="report-section smart-money"><h2>Smart Money Accumulation</h2>'
            '<p class="section-note">Confirmation and rotation intelligence only. '
            "Congressional disclosures may lag transaction dates; 13F holdings are "
            "quarter-end snapshots and are not trade-timing signals.</p>"
            f"{congress_table}{institution_table}</section>"
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
    def _flow_rows(candidates: tuple[ResearchCandidate, ...]) -> str:
        return "".join(
            "<tr>"
            f"<td><strong>{escape(item.symbol)}</strong></td>"
            f"<td>{escape(item.option_contract or 'Contract unavailable')}</td>"
            f"<td>{item.option_volume:,}</td>"
            f"<td>{item.option_open_interest:,}</td>"
            f"<td>{item.option_volume_oi_ratio:.2f}x</td>"
            f"<td>{item.option_bid:.2f} / {item.option_ask:.2f}</td>"
            f"<td>{escape(item.flow_classification or '')}</td>"
            "</tr>"
            for item in candidates
            if item.option_volume_oi_ratio is not None
            and item.option_bid is not None
            and item.option_ask is not None
        )

    @staticmethod
    def _flow_table(
        heading: str,
        candidates: tuple[ResearchCandidate, ...],
        *,
        empty_message: str,
    ) -> str:
        rows = NewsletterRenderer._flow_rows(candidates)
        if not rows:
            return (
                f"<h3>{escape(heading)}</h3>"
                f'<p class="section-note">{escape(empty_message)}</p>'
            )
        return (
            f"<h3>{escape(heading)}</h3>"
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Company</th><th>Contract</th><th>Volume</th><th>Open interest</th>"
            "<th>Volume/OI</th><th>Bid / Ask</th><th>Classification</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )

    @staticmethod
    def _unusual_options_section(
        candidates: tuple[ResearchCandidate, ...],
    ) -> str:
        unusual = tuple(
            item
            for item in candidates
            if item.flow_classification == "UNUSUAL_CONFIRMATION"
        )
        flow_observed = any(item.flow_classification is not None for item in candidates)

        if unusual:
            calls = tuple(
                item
                for item in unusual
                if NewsletterRenderer._option_side(item) == "CALL"
            )
            puts = tuple(
                item
                for item in unusual
                if NewsletterRenderer._option_side(item) == "PUT"
            )
            unknown = tuple(
                item
                for item in unusual
                if NewsletterRenderer._option_side(item) == "UNKNOWN"
            )
            body = NewsletterRenderer._flow_table(
                "Unusual CALL Activity",
                calls,
                empty_message=(
                    "No shortlisted CALL contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
            body += NewsletterRenderer._flow_table(
                "Unusual PUT Activity",
                puts,
                empty_message=(
                    "No shortlisted PUT contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
            if unknown:
                body += NewsletterRenderer._flow_table(
                    "Unclassified Option-Side Activity",
                    unknown,
                    empty_message="",
                )
        elif flow_observed:
            body = NewsletterRenderer._flow_table(
                "Unusual CALL Activity",
                (),
                empty_message=(
                    "No shortlisted CALL contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
            body += NewsletterRenderer._flow_table(
                "Unusual PUT Activity",
                (),
                empty_message=(
                    "No shortlisted PUT contract met the unusual-activity threshold "
                    "for this report."
                ),
            )
        else:
            body = (
                '<p class="data-warning"><strong>ORATS flow data unavailable.</strong> '
                "No unusual-options conclusion is reported for this run.</p>"
            )

        return (
            '<section class="report-section unusual-options">'
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
        rows = "".join(
            NewsletterRenderer._candidate_row(candidate) for candidate in candidates
        )
        heading = disposition.value.replace("_", " ").title()
        return (
            f'<section class="report-section"><h2>{escape(heading)}</h2>'
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Symbol</th><th>Signal</th><th>Instrument</th><th>Sector</th>"
            "<th>Thesis and evidence</th><th>Risk/Data</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div></section>"
        )

    @staticmethod
    def _candidate_row(candidate: ResearchCandidate) -> str:
        reasons = ", ".join(candidate.reasons)
        contract = (
            f"<br><small>{escape(candidate.option_contract)}</small>"
            if candidate.option_contract
            else ""
        )
        evidence = f"{escape(candidate.thesis)}<br><small>{escape(reasons)}</small>"
        statuses = f"{escape(candidate.risk_status)} / {escape(candidate.data_status)}"
        return (
            "<tr>"
            f"<td><strong>{escape(candidate.symbol)}</strong></td>"
            f"<td>{escape(candidate.signal_label)}</td>"
            f"<td>{escape(candidate.instrument.value)}{contract}</td>"
            f"<td>{escape(candidate.sector)}</td>"
            f"<td>{evidence}</td>"
            f"<td>{statuses}</td>"
            "</tr>"
        )

    @staticmethod
    def _document(packet: DailyResearchPacket, content: str) -> str:
        disclosures = "".join(f"<li>{escape(item)}</li>" for item in packet.disclosures)
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{RESEARCH_PRODUCT} — {escape(packet.report_date)}</title>
<style>
@page {{ size: Letter; margin: 0.6in; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #172033; background: #fff; font: 12pt/1.45 Arial, sans-serif; }}
header {{ border-bottom: 3px solid #aa7a24; padding-bottom: 14px; margin-bottom: 22px; }}
h1 {{ margin: 0; font: 700 25pt/1.15 Georgia, serif; }}
h2 {{ margin: 0 0 12px; font-size: 17pt; color: #17365d; }}
h3 {{ margin: 18px 0 9px; font-size: 13pt; color: #17365d; }}
.brand-kicker {{ margin-bottom: 4px; font-size: 9.5pt; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #aa7a24; }}
.brand-line {{ margin-top: 7px; font-size: 10.5pt; color: #344256; }}
.company-line {{ margin-top: 2px; font-size: 9.5pt; color: #6a7482; }}
.meta {{ margin-top: 10px; font-size: 10.5pt; color: #526071; }}
.section-note {{ margin: 0 0 12px; font-size: 10pt; color: #526071; }}
.report-section {{ margin: 0 0 26px; break-inside: avoid-page; page-break-inside: avoid; }}
.table-wrap {{ width: 100%; overflow-wrap: anywhere; margin-bottom: 12px; }}
table {{ width: 100%; border-collapse: collapse; table-layout: auto; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{ border: 1px solid #c9d1dc; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #17365d; color: white; font-size: 10pt; }}
td {{ font-size: 10.5pt; }}
small {{ font-size: 9pt; color: #526071; }}
footer {{ border-top: 1px solid #c9d1dc; margin-top: 24px; padding-top: 12px; font-size: 9.5pt; }}
.footer-brand {{ margin-bottom: 10px; color: #344256; }}
@media screen and (max-width: 760px) {{ .table-wrap {{ overflow-x: auto; }} table {{ min-width: 720px; }} }}
</style>
</head>
<body>
<header>
<div class="brand-kicker">{RESEARCH_PRODUCT}</div>
<h1>{escape(NEWSLETTER_TITLE)}</h1>
<div class="brand-line">Quantitative Intelligence by <strong>{INSTITUTIONAL_BRAND}</strong></div>
<div class="company-line">A {PARENT_COMPANY} Company</div>
<div class="meta">{escape(packet.report_date)} · Run {escape(packet.run_id)} · Method {escape(packet.methodology_version)} · Regime {escape(packet.market_regime)}</div>
</header>
<main>{content or "<section><h2>No publishable candidates</h2><p>The research engine produced no eligible records for this run.</p></section>"}</main>
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
        if "font-size: 8" in html or "font-size: 7" in html:
            warnings.append("TEXT_TOO_SMALL")
        if "Unusual Options Activity" not in html:
            warnings.append("UNUSUAL_OPTIONS_SECTION_MISSING")
        if "Unusual CALL Activity" not in html and any(
            candidate.flow_classification is not None for candidate in packet.candidates
        ):
            warnings.append("UNUSUAL_CALL_SECTION_MISSING")
        if "Unusual PUT Activity" not in html and any(
            candidate.flow_classification is not None for candidate in packet.candidates
        ):
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
