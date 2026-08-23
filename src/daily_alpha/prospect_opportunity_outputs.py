"""V1 prospect/subscriber output channels backed by one canonical opportunity board."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from html import escape

from .prospect_opportunity_board import (
    OpportunityBoardFilter,
    ProspectOpportunity,
    ProspectOpportunityBoard,
)


class ProspectOutputChannel(StrEnum):
    NEWSLETTER = "NEWSLETTER"
    DASHBOARD = "DASHBOARD"
    API = "API"


class ProspectOpportunityOutputError(ValueError):
    """A V1 prospect output violated canonical-board presentation rules."""


@dataclass(frozen=True, slots=True)
class ProspectOpportunityOutput:
    channel: ProspectOutputChannel
    board_id: str
    total_qualifying: int
    top_picks: tuple[ProspectOpportunity, ...]
    complete_qualifying: tuple[ProspectOpportunity, ...]
    filtered_count: int
    signal_context: str
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.board_id.strip():
            raise ProspectOpportunityOutputError("BOARD_ID_REQUIRED")
        if self.total_qualifying != len(self.complete_qualifying):
            raise ProspectOpportunityOutputError("COMPLETE_SET_COUNT_MISMATCH")
        if len(self.top_picks) > 3:
            raise ProspectOpportunityOutputError("TOP_PICKS_EXCEED_V1_LIMIT")
        canonical_ids = tuple(item.candidate_id for item in self.complete_qualifying)
        top_ids = tuple(item.candidate_id for item in self.top_picks)
        if top_ids != canonical_ids[: len(top_ids)]:
            raise ProspectOpportunityOutputError("TOP_PICKS_MUST_PREFIX_CANONICAL_SET")
        if self.trading_authorized or self.live_trading_enabled:
            raise ProspectOpportunityOutputError("PROSPECT_OUTPUT_CANNOT_AUTHORIZE_TRADING")

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel.value,
            "board_id": self.board_id,
            "total_qualifying": self.total_qualifying,
            "top_picks": [item.to_dict() for item in self.top_picks],
            "complete_qualifying": [item.to_dict() for item in self.complete_qualifying],
            "filtered_count": self.filtered_count,
            "signal_context": self.signal_context,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


@dataclass(frozen=True, slots=True)
class ProspectOpportunityAPIPage:
    """Bounded API query view over one immutable canonical opportunity board."""

    board_id: str
    filter_id: str
    offset: int
    limit: int
    total_qualifying: int
    total_matched: int
    opportunities: tuple[ProspectOpportunity, ...]
    has_more: bool
    signal_context: str
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.board_id.strip():
            raise ProspectOpportunityOutputError("API_PAGE_BOARD_ID_REQUIRED")
        if not self.filter_id.strip():
            raise ProspectOpportunityOutputError("API_PAGE_FILTER_ID_REQUIRED")
        if self.total_qualifying < self.total_matched:
            raise ProspectOpportunityOutputError("API_PAGE_MATCHED_TOTAL_EXCEEDS_CANONICAL_TOTAL")
        if self.total_matched < len(self.opportunities):
            raise ProspectOpportunityOutputError(
                "API_PAGE_MATCHED_TOTAL_CANNOT_BE_SMALLER_THAN_PAGE"
            )
        if self.trading_authorized or self.live_trading_enabled:
            raise ProspectOpportunityOutputError("PROSPECT_API_PAGE_CANNOT_AUTHORIZE_TRADING")

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": ProspectOutputChannel.API.value,
            "board_id": self.board_id,
            "filter_id": self.filter_id,
            "offset": self.offset,
            "limit": self.limit,
            "total_qualifying": self.total_qualifying,
            "total_matched": self.total_matched,
            "opportunities": [item.to_dict() for item in self.opportunities],
            "has_more": self.has_more,
            "signal_context": self.signal_context,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


def build_prospect_output(
    board: ProspectOpportunityBoard,
    *,
    channel: ProspectOutputChannel,
) -> ProspectOpportunityOutput:
    """Project one canonical board into a V1 customer-facing output channel."""
    return ProspectOpportunityOutput(
        channel=channel,
        board_id=board.board_id,
        total_qualifying=board.total_qualifying,
        top_picks=board.top_picks,
        complete_qualifying=board.opportunities,
        filtered_count=len(board.filtered),
        signal_context=board.signal_context,
    )


def build_all_v1_prospect_outputs(
    board: ProspectOpportunityBoard,
) -> tuple[ProspectOpportunityOutput, ...]:
    """Build NEWSLETTER, DASHBOARD and API outputs from the same exact board."""
    return tuple(
        build_prospect_output(board, channel=channel) for channel in ProspectOutputChannel
    )


def build_prospect_api_page(
    board: ProspectOpportunityBoard,
    *,
    query: OpportunityBoardFilter | None = None,
    offset: int = 0,
    limit: int = 50,
) -> ProspectOpportunityAPIPage:
    """Create a paginated/filterable API view without changing discovery membership or rank."""
    page = board.page(offset=offset, limit=limit, query=query)
    return ProspectOpportunityAPIPage(
        board_id=page.board_id,
        filter_id=page.filter_id,
        offset=page.offset,
        limit=page.limit,
        total_qualifying=page.total_qualifying,
        total_matched=page.total_matched,
        opportunities=page.opportunities,
        has_more=page.has_more,
        signal_context=board.signal_context,
    )


def render_prospect_newsletter_html(board: ProspectOpportunityBoard) -> str:
    """Render the V1 prospect newsletter: Top 3 first, then every other qualifier."""
    output = build_prospect_output(board, channel=ProspectOutputChannel.NEWSLETTER)
    top_cards = "".join(_top_pick_card(item) for item in output.top_picks)
    if not top_cards:
        top_cards = (
            '<p class="empty">No opportunities currently meet the governed '
            "qualification gates.</p>"
        )

    additional = output.complete_qualifying[len(output.top_picks) :]
    additional_rows = "".join(_opportunity_row(item) for item in additional)
    if additional_rows:
        additional_section = (
            '<section class="full-board"><h2>Additional Qualified Opportunities</h2>'
            '<p>Every remaining valid setup is retained below in canonical rank order.</p>'
            '<table><thead><tr><th>Rank</th><th>Symbol</th><th>Status</th>'
            '<th>Score</th><th>Sector</th><th>Theme</th><th>Expression</th></tr></thead>'
            f'<tbody>{additional_rows}</tbody></table></section>'
        )
    else:
        additional_section = (
            '<section class="full-board"><h2>Additional Qualified Opportunities</h2>'
            '<p>No additional qualifying opportunities beyond the featured set.</p></section>'
        )

    canonical_ids = ",".join(item.candidate_id for item in output.complete_qualifying)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Alpha Research — ConvexRidge Picks</title>
<style>
body {{ margin: 0; padding: 24px; font: 12pt/1.45 Arial, sans-serif; color: #172033; }}
h1, h2 {{ color: #13294b; }}
.meta {{ color: #607084; font-size: 10pt; overflow-wrap: break-word; }}
.top-grid {{ display: flex; flex-wrap: wrap; gap: 12px; }}
.top-card {{ flex: 1 1 220px; padding: 16px; border: 1px solid #dce2ea; border-top: 4px solid #967326; }}
.rank {{ font-weight: 800; color: #967326; }}
.symbol {{ font-size: 18pt; font-weight: 800; color: #13294b; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th, td {{ padding: 8px; text-align: left; border: 1px solid #dce2ea; overflow-wrap: break-word; }}
th {{ background: #13294b; color: white; }}
.disclosure {{ margin-top: 24px; padding-top: 12px; border-top: 1px solid #dce2ea; color: #607084; font-size: 9.5pt; }}
</style>
</head>
<body data-board-id="{escape(output.board_id)}" data-total-qualifying="{output.total_qualifying}" data-canonical-candidate-ids="{escape(canonical_ids)}">
<header>
<div class="meta">Daily Alpha Research · ConvexRidge · Canonical board {escape(output.board_id)} · {output.total_qualifying} qualifying opportunities</div>
<h1>Top 3 ConvexRidge Picks</h1>
<p>Highest-ranked governed research/model signals for immediate attention. The complete qualifying set remains available below.</p>
</header>
<section class="top-grid">{top_cards}</section>
{additional_section}
<div class="disclosure">{escape(output.signal_context)} · Rankings do not authorize portfolio allocation or execution. Trading authorization: false. Live trading: false.</div>
</body>
</html>"""


def _top_pick_card(item: ProspectOpportunity) -> str:
    details: list[str] = []
    if item.thesis:
        details.append(f"<div><strong>Thesis:</strong> {escape(item.thesis)}</div>")
    if item.price is not None or item.average_volume is not None:
        liquidity: list[str] = []
        if item.price is not None:
            liquidity.append(f"price ${item.price:,.2f}")
        if item.average_volume is not None:
            liquidity.append(f"30D avg volume {item.average_volume:,.0f}")
        details.append(
            f'<div><strong>Liquidity:</strong> {escape(" · ".join(liquidity))}</div>'
        )
    if item.invalidation:
        details.append(
            f"<div><strong>Invalidation:</strong> {escape(item.invalidation)}</div>"
        )
    return (
        '<article class="top-card">'
        f'<div class="rank">Rank #{item.rank}</div>'
        f'<div class="symbol">{escape(item.symbol)}</div>'
        f'<div>{escape(item.lifecycle_status)} · Score {item.score:.2f}</div>'
        f'<div>{escape(item.sector)} · {escape(item.theme)} · '
        f'{escape(item.instrument_selected)}</div>'
        + "".join(details)
        + "</article>"
    )


def _opportunity_row(item: ProspectOpportunity) -> str:
    return (
        "<tr>"
        f"<td>{item.rank}</td>"
        f"<td>{escape(item.symbol)}</td>"
        f"<td>{escape(item.lifecycle_status)}</td>"
        f"<td>{item.score:.2f}</td>"
        f"<td>{escape(item.sector)}</td>"
        f"<td>{escape(item.theme)}</td>"
        f"<td>{escape(item.instrument_selected)}</td>"
        "</tr>"
    )


__all__ = [
    "ProspectOpportunityAPIPage",
    "ProspectOpportunityOutput",
    "ProspectOpportunityOutputError",
    "ProspectOutputChannel",
    "build_all_v1_prospect_outputs",
    "build_prospect_api_page",
    "build_prospect_output",
    "render_prospect_newsletter_html",
]
