"""Day-over-day OVTLYR research ranking for Daily Alpha.

This module is stock-first and vendor-independent. It does not fetch option chains,
select option contracts, or use derivatives data to alter stock eligibility or
ranking. Options are user-directed and broker-chain sourced separately.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .ovtlyr import (
    ClassifiedRecord,
    OvtlyrRecord,
    OvtlyrStatus,
    SectorRotation,
    compare_universes,
    load_ovtlyr_csv,
    summarize_sector_rotation,
)
from .smart_money import (
    CongressionalAccumulation,
    InstitutionalAccumulation,
    smart_money_bonus,
)
from .trump_policy import TrumpPolicyCompany, trump_policy_bonus

ACTIONABLE_STATUSES = {
    OvtlyrStatus.NEW_BUY,
    OvtlyrStatus.EMERGING,
    OvtlyrStatus.LEADER,
    OvtlyrStatus.ENTRY_WATCH,
    OvtlyrStatus.RE_ENTRY,
}

_DATE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})")
CANONICAL_COMPANY_MIN_AVERAGE_VOLUME = 1_500_000.0


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
    options_mode: str = "USER_DIRECTED_BROKER_CHAIN"
    smart_money_bonus: float = 0.0
    congressional_rank: int | None = None
    institutional_rank: int | None = None
    trump_policy_bonus: float = 0.0
    trump_policy_rank: int | None = None

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
    congressional: tuple[CongressionalAccumulation, ...] = ()
    institutional: tuple[InstitutionalAccumulation, ...] = ()
    trump_policy: tuple[TrumpPolicyCompany, ...] = ()


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
    congressional: tuple[CongressionalAccumulation, ...] = (),
    institutional: tuple[InstitutionalAccumulation, ...] = (),
    trump_policy: tuple[TrumpPolicyCompany, ...] = (),
    min_company_average_volume: float | None = None,
) -> ResearchShortlistResult:
    """Rank actionable stock research without any option-chain dependency."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if min_company_average_volume is not None and min_company_average_volume < 0:
        raise ValueError("min_company_average_volume must be non-negative")

    previous = load_ovtlyr_csv(previous_path)
    current = load_ovtlyr_csv(current_path)
    current_by_symbol = {record.symbol: record for record in current}
    classifications = compare_universes(previous, current)
    rotations = summarize_sector_rotation(classifications)
    sector_scores = {item.sector: item.net_score for item in rotations}
    congressional_ranks = {item.symbol.upper(): item.rank for item in congressional}
    institutional_ranks = {
        item.symbol.upper(): item.rank for item in institutional if item.symbol
    }
    policy_ranks = {item.symbol.upper(): item.rank for item in trump_policy}

    items: list[ResearchShortlistItem] = []
    excluded_partial = 0
    excluded_liquidity_filtered = 0
    excluded_liquidity_missing = 0
    non_optionable_count = 0
    smart_money_matched = 0
    policy_matched = 0

    for classified in classifications:
        source = current_by_symbol.get(classified.symbol)
        if (
            source is None
            or source.signal != "BUY"
            or classified.status not in ACTIONABLE_STATUSES
        ):
            continue
        if source.partial_data:
            excluded_partial += 1
            continue
        if min_company_average_volume is not None:
            if source.average_volume <= 0:
                excluded_liquidity_missing += 1
                continue
            if source.average_volume <= min_company_average_volume:
                excluded_liquidity_filtered += 1
                continue
        if source.optionable is False:
            non_optionable_count += 1

        smart_bonus = smart_money_bonus(source.symbol, congressional, institutional)
        policy_bonus = trump_policy_bonus(source.symbol, trump_policy)
        if smart_bonus > 0:
            smart_money_matched += 1
        if policy_bonus > 0:
            policy_matched += 1
        score = _base_score(
            classified,
            source,
            sector_scores.get(source.sector, 0),
        ) + smart_bonus + policy_bonus
        items.append(
            ResearchShortlistItem(
                symbol=source.symbol,
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
                smart_money_bonus=smart_bonus,
                congressional_rank=congressional_ranks.get(source.symbol.upper()),
                institutional_rank=institutional_ranks.get(source.symbol.upper()),
                trump_policy_bonus=policy_bonus,
                trump_policy_rank=policy_ranks.get(source.symbol.upper()),
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
        "company_average_volume_gate_enabled": min_company_average_volume is not None,
        "company_min_average_volume": min_company_average_volume,
        "excluded_liquidity_filtered": excluded_liquidity_filtered,
        "excluded_liquidity_missing": excluded_liquidity_missing,
        "excluded_partial_data": excluded_partial,
        "non_optionable_metadata_count": non_optionable_count,
        "options_mode": "USER_DIRECTED_BROKER_CHAIN",
        "options_affect_stock_eligibility": False,
        "options_affect_stock_score": False,
        "smart_money_congressional_count": len(congressional),
        "smart_money_institutional_count": len(institutional),
        "smart_money_matched_candidates": smart_money_matched,
        "smart_money_max_bonus": 15.0,
        "smart_money_research_ranking_only": True,
        "trump_policy_company_count": len(trump_policy),
        "trump_policy_matched_candidates": policy_matched,
        "trump_policy_max_bonus": 5.0,
        "trump_policy_research_ranking_only": True,
        "external_confirmation_max_bonus": 20.0,
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
        congressional=congressional,
        institutional=institutional,
        trump_policy=trump_policy,
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
    smart_money_json = destination / "smart_money.json"
    trump_policy_json = destination / "trump_policy.json"
    summary_json = destination / "summary.json"

    rows = [
        {"rank": rank, **item.to_dict()}
        for rank, item in enumerate(result.items, start=1)
    ]
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
    smart_money_json.write_text(
        json.dumps(
            {
                "congressional": [item.to_dict() for item in result.congressional],
                "institutional": [item.to_dict() for item in result.institutional],
                "weights": {
                    "congressional_max": 5.0,
                    "institutional_max": 10.0,
                    "combined_max": 15.0,
                },
                "research_ranking_only": True,
                "trading_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    trump_policy_json.write_text(
        json.dumps(
            {
                "companies": [item.to_dict() for item in result.trump_policy],
                "max_bonus": 5.0,
                "label": "Trump Administration Company & Policy Watch",
                "not_presidential_stock_recommendations": True,
                "research_ranking_only": True,
                "trading_authorized": False,
            },
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
        "smart_money_json": smart_money_json,
        "trump_policy_json": trump_policy_json,
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
    if source.momentum in {
        "ACCELERATING",
        "STRONG",
        "RISING",
        "POSITIVE",
        "MOVING UP",
    }:
        points += 10
    points += max(-10.0, min(15.0, sector_net_score / 10))
    if source.price > 0 and source.average_volume > 0:
        dollar_volume = source.price * source.average_volume
        if dollar_volume >= 100_000_000:
            points += 5
        elif dollar_volume >= 20_000_000:
            points += 3
    return round(points, 2)
