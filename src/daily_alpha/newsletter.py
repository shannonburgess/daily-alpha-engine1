"""Readable, deterministic HTML rendering for Daily Alpha research packets."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .research_report import DailyResearchPacket, ResearchCandidate, ResearchDisposition


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
<title>Daily Alpha — {escape(packet.report_date)}</title>
<style>
@page {{ size: Letter; margin: 0.6in; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #172033; background: #fff; font: 12pt/1.45 Arial, sans-serif; }}
header {{ border-bottom: 3px solid #aa7a24; padding-bottom: 14px; margin-bottom: 22px; }}
h1 {{ margin: 0; font: 700 25pt/1.15 Georgia, serif; }}
h2 {{ margin: 0 0 12px; font-size: 17pt; color: #17365d; }}
.meta {{ margin-top: 8px; font-size: 10.5pt; color: #526071; }}
.report-section {{ margin: 0 0 26px; break-inside: avoid-page; page-break-inside: avoid; }}
.table-wrap {{ width: 100%; overflow-wrap: anywhere; }}
table {{ width: 100%; border-collapse: collapse; table-layout: auto; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{ border: 1px solid #c9d1dc; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #17365d; color: white; font-size: 10pt; }}
td {{ font-size: 10.5pt; }}
small {{ font-size: 9pt; color: #526071; }}
footer {{ border-top: 1px solid #c9d1dc; margin-top: 24px; padding-top: 12px; font-size: 9.5pt; }}
@media screen and (max-width: 760px) {{ .table-wrap {{ overflow-x: auto; }} table {{ min-width: 720px; }} }}
</style>
</head>
<body>
<header>
<h1>Daily Alpha &amp; Risk</h1>
<div class="meta">{escape(packet.report_date)} · Run {escape(packet.run_id)} · Method {escape(packet.methodology_version)} · Regime {escape(packet.market_regime)}</div>
</header>
<main>{content or "<section><h2>No publishable candidates</h2><p>The research engine produced no eligible records for this run.</p></section>"}</main>
<footer><strong>Disclosures</strong><ul>{disclosures}</ul></footer>
</body>
</html>"""

    @staticmethod
    def _quality_checks(html: str, packet: DailyResearchPacket) -> tuple[str, ...]:
        warnings: list[str] = []
        if "height:" in html or "max-height:" in html:
            warnings.append("FIXED_HEIGHT_LAYOUT_DETECTED")
        if "font-size: 8" in html or "font-size: 7" in html:
            warnings.append("TEXT_TOO_SMALL")
        if any(escape(candidate.symbol) not in html for candidate in packet.candidates):
            warnings.append("CANDIDATE_CONTENT_MISSING")
        if any(escape(item) not in html for item in packet.disclosures):
            warnings.append("DISCLOSURE_MISSING")
        return tuple(warnings)
