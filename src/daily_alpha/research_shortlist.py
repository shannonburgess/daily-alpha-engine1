"""Day-over-day OVTLYR ranking with quota-aware ORATS research enrichment.

This module builds a newsletter/research shortlist only. It does not consume Pine
signals, run the portfolio risk gate, create paper trades, or enable live trading.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import OptionQualityRules
from .models import OptionCandidate
from .ovtlyr import (
    ClassifiedRecord,
    OvtlyrRecord,
    OvtlyrStatus,
    SectorRotation,
    compare_universes,
    load_ovtlyr_csv,
    summarize_sector_rotation,
)
from .sources import OratsBatchSource

ACTIONABLE_STATUSES = {
    OvtlyrStatus.NEW_BUY,
    OvtlyrStatus.EMERGING,
    OvtlyrStatus.LEADER,
    OvtlyrStatus.ENTRY_WATCH,
    OvtlyrStatus.RE_ENTRY,
}

_DATE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})")


@dataclass(frozen=True)
class ResearchShortlistItem:
    symbol: str
    ovtlyr_status: str
    display_label: str
    classification_reason: str
    score: float
    sector: str
    industry: str
    sector_net_score: int
    trend: str
    momentum: str
    optionable: bool | None
    price: float
    average_volume: float
    orats_status: str
    orats_reason: str
    selected_expiration: str = ""
    selected_strike: float = 0.0
    selected_option_type: str = ""
    selected_delta: float | None = None
    selected_bid: float = 0.0
    selected_ask: float = 0.0
    selected_spread_pct: float | None = None
    selected_open_interest: int = 0
    selected_volume: int = 0
    unusual_options_activity: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchShortlistResult:
    previous_file: str
    current_file: str
    generated_at: str
    items: tuple[ResearchShortlistItem, ...]
    classifications: tuple[ClassifiedRecord, ...]
    sector_rotation: tuple[SectorRotation, ...]
    summary: dict[str, Any]


def discover_daily_pair(root: str | Path) -> tuple[Path, Path]:
    """Select the two newest dated OVTLYR CSVs by filename, not download mtime."""
    directory = Path(root)
    candidates: list[tuple[str, str, Path]] = []
    for path in directory.glob("*.csv"):
        match = _DATE_PATTERN.search(path.name)
        if match and path.is_file() and path.stat().st_size > 0:
            candidates.append((match.group(1), path.name, path))
    candidates.sort()
    if len(candidates) < 2:
        raise ValueError("At least two dated OVTLYR CSV files are required")
    return candidates[-2][2], candidates[-1][2]


def build_research_shortlist(
    previous_path: str | Path,
    current_path: str | Path,
    *,
    as_of: datetime,
    orats_source: OratsBatchSource,
    request_limit: int = 20,
    option_rules: OptionQualityRules | None = None,
) -> ResearchShortlistResult:
    """Rank day-over-day OVTLYR changes, then enrich only the best candidates."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if request_limit <= 0:
        raise ValueError("request_limit must be positive")

    previous = load_ovtlyr_csv(previous_path)
    current = load_ovtlyr_csv(current_path)
    current_by_symbol = {record.symbol: record for record in current}
    classifications = compare_universes(previous, current)
    rotations = summarize_sector_rotation(classifications)
    sector_scores = {item.sector: item.net_score for item in rotations}

    staged: list[tuple[ClassifiedRecord, OvtlyrRecord, float]] = []
    excluded_not_optionable = 0
    excluded_partial = 0
    for classified in classifications:
        source = current_by_symbol.get(classified.symbol)
        if source is None or source.signal != "BUY" or classified.status not in ACTIONABLE_STATUSES:
            continue
        if source.partial_data:
            excluded_partial += 1
            continue
        if source.optionable is False:
            excluded_not_optionable += 1
            continue
        score = _base_score(classified, source, sector_scores.get(source.sector, 0))
        staged.append((classified, source, score))

    staged.sort(key=lambda row: (-row[2], row[1].symbol))
    requested = tuple(row[1].symbol for row in staged[:request_limit])
    batch = orats_source.fetch(requested, as_of=as_of)
    chains = {chain.ticker: chain for chain in batch.chains}
    errors = dict(batch.errors)
    requested_set = set(requested)
    rules = option_rules or OptionQualityRules()

    items: list[ResearchShortlistItem] = []
    qualified_count = 0
    data_error_count = 0
    for classified, source, base_score in staged:
        symbol = source.symbol
        selected: OptionCandidate | None = None
        score = base_score
        if symbol not in requested_set:
            orats_status = "NOT_REQUESTED"
            orats_reason = "API_LIMIT_REACHED"
        elif symbol in errors:
            data_error_count += 1
            orats_status = "DATA_ERROR"
            orats_reason = errors[symbol]
        else:
            chain = chains.get(symbol)
            if chain is None:
                data_error_count += 1
                orats_status = "DATA_ERROR"
                orats_reason = "ORATS_CHAIN_MISSING"
            else:
                selected = _best_qualified_option(chain.candidates, rules)
                if selected is None:
                    orats_status = "ENRICHED"
                    orats_reason = "NO_OPTION_PASSED_QUALITY_FILTERS"
                else:
                    qualified_count += 1
                    orats_status = "ENRICHED"
                    orats_reason = "QUALIFIED_OPTION_FOUND"
                    score += 20.0
                    score += max(0.0, 10.0 - 50.0 * selected.spread_pct)
                    score += min(5.0, selected.volume_to_open_interest * 5.0)

        items.append(
            ResearchShortlistItem(
                symbol=symbol,
                ovtlyr_status=classified.status.value,
                display_label=classified.display_label,
                classification_reason=classified.reason,
                score=round(score, 2),
                sector=source.sector,
                industry=source.industry,
                sector_net_score=sector_scores.get(source.sector, 0),
                trend=source.trend,
                momentum=source.momentum,
                optionable=source.optionable,
                price=source.price,
                average_volume=source.average_volume,
                orats_status=orats_status,
                orats_reason=orats_reason,
                selected_expiration=selected.expiration if selected else "",
                selected_strike=selected.strike if selected else 0.0,
                selected_option_type=selected.option_type if selected else "",
                selected_delta=selected.delta if selected else None,
                selected_bid=selected.bid if selected else 0.0,
                selected_ask=selected.ask if selected else 0.0,
                selected_spread_pct=(round(selected.spread_pct, 6) if selected else None),
                selected_open_interest=selected.open_interest if selected else 0,
                selected_volume=selected.volume if selected else 0,
                unusual_options_activity=(
                    selected is not None and selected.volume_to_open_interest >= 1.0
                ),
            )
        )

    ranked = tuple(sorted(items, key=lambda item: (-item.score, item.symbol)))
    status_counts = {status.value: 0 for status in OvtlyrStatus}
    for classified in classifications:
        status_counts[classified.status.value] += 1

    summary = {
        "previous_file": Path(previous_path).name,
        "current_file": Path(current_path).name,
        "generated_at": as_of.isoformat(),
        "current_universe_count": len(current),
        "current_buy_count": sum(record.signal == "BUY" for record in current),
        "actionable_ranked_count": len(ranked),
        "excluded_not_optionable": excluded_not_optionable,
        "excluded_partial_data": excluded_partial,
        "orats_requests": len(requested),
        "orats_request_limit": request_limit,
        "qualified_option_count": qualified_count,
        "orats_data_error_count": data_error_count,
        "classification_counts": status_counts,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    return ResearchShortlistResult(
        previous_file=Path(previous_path).name,
        current_file=Path(current_path).name,
        generated_at=as_of.isoformat(),
        items=ranked,
        classifications=tuple(classifications),
        sector_rotation=tuple(rotations),
        summary=summary,
    )


def write_research_shortlist_outputs(
    output_dir: str | Path,
    result: ResearchShortlistResult,
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    shortlist_json = destination / "shortlist.json"
    shortlist_csv = destination / "shortlist.csv"
    classifications_json = destination / "classifications.json"
    sector_json = destination / "sector_rotation.json"
    summary_json = destination / "summary.json"

    rows = []
    for rank, item in enumerate(result.items, start=1):
        row = {"rank": rank, **item.to_dict()}
        rows.append(row)
    shortlist_json.write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with shortlist_csv.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    classifications_json.write_text(
        json.dumps(
            [item.to_dict() for item in result.classifications],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    sector_json.write_text(
        json.dumps(
            [asdict(item) for item in result.sector_rotation],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    summary_json.write_text(
        json.dumps(result.summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "shortlist_json": shortlist_json,
        "shortlist_csv": shortlist_csv,
        "classifications_json": classifications_json,
        "sector_rotation_json": sector_json,
        "summary_json": summary_json,
    }


def _base_score(
    classified: ClassifiedRecord,
    source: OvtlyrRecord,
    sector_net_score: int,
) -> float:
    status_points = {
        OvtlyrStatus.EMERGING: 40,
        OvtlyrStatus.NEW_BUY: 36,
        OvtlyrStatus.RE_ENTRY: 34,
        OvtlyrStatus.ENTRY_WATCH: 30,
        OvtlyrStatus.LEADER: 26,
    }.get(classified.status, 0)
    points = float(status_points)
    if source.trend in {"UP", "UPTREND", "BULLISH", "RISING"}:
        points += 10
    if source.momentum in {"ACCELERATING", "STRONG", "RISING", "POSITIVE", "MOVING UP"}:
        points += 10
    points += max(-10.0, min(15.0, sector_net_score / 10))
    if source.optionable is True:
        points += 3
    if source.price > 0 and source.average_volume > 0:
        dollar_volume = source.price * source.average_volume
        if dollar_volume >= 100_000_000:
            points += 5
        elif dollar_volume >= 20_000_000:
            points += 3
    return round(points, 2)


def _best_qualified_option(
    candidates: tuple[OptionCandidate, ...],
    rules: OptionQualityRules,
) -> OptionCandidate | None:
    qualified = [item for item in candidates if _option_passes(item, rules)]
    if not qualified:
        return None
    return min(
        qualified,
        key=lambda item: (item.spread_pct, -item.open_interest, -item.volume),
    )


def _option_passes(option: OptionCandidate, rules: OptionQualityRules) -> bool:
    return (
        rules.min_dte <= option.dte <= rules.max_dte
        and option.bid >= rules.min_bid
        and option.ask >= option.bid
        and option.spread_pct <= rules.max_spread_pct
        and option.open_interest >= rules.min_open_interest
        and option.volume >= rules.min_volume
        and (
            option.delta is None
            or rules.min_abs_delta <= abs(option.delta) <= rules.max_abs_delta
        )
    )
