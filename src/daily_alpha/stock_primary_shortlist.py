"""Canonical stock-primary actionable shortlist for Daily Alpha.

Stock eligibility and ranking are derived from OVTLYR, canonical liquidity/price
controls, and bounded research confirmations. Automated option-chain enrichment is
not part of this path. Options are user-directed and broker-chain sourced.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .ovtlyr import (
    ClassifiedRecord,
    OvtlyrRecord,
    OvtlyrStatus,
    compare_universes,
    load_ovtlyr_csv,
    summarize_sector_rotation,
)
from .research_shortlist import ResearchShortlistItem, ResearchShortlistResult
from .smart_money import (
    CongressionalAccumulation,
    InstitutionalAccumulation,
    smart_money_bonus,
)
from .trump_policy import TrumpPolicyCompany, trump_policy_bonus

STOCK_PRIMARY_ACTIONABLE_STATUSES = {
    OvtlyrStatus.NEW_BUY,
    OvtlyrStatus.EMERGING,
    OvtlyrStatus.LEADER,
    OvtlyrStatus.ENTRY_WATCH,
    OvtlyrStatus.RE_ENTRY,
}

CANONICAL_COMPANY_MIN_PRICE = 10.0


def build_stock_primary_shortlist(
    previous_path: str | Path,
    current_path: str | Path,
    *,
    as_of: datetime,
    congressional: tuple[CongressionalAccumulation, ...] = (),
    institutional: tuple[InstitutionalAccumulation, ...] = (),
    trump_policy: tuple[TrumpPolicyCompany, ...] = (),
    company_symbols: frozenset[str] | None = None,
    min_company_price: float = CANONICAL_COMPANY_MIN_PRICE,
) -> ResearchShortlistResult:
    """Build the stock-primary Daily Alpha shortlist without derivatives data.

    ``company_symbols`` should come from the same canonical liquidity evidence used
    to pre-filter the OVTLYR files. When supplied, the broad $10 floor applies to
    individual companies only; ETFs retain their separate liquidity/capacity path.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if min_company_price <= 0:
        raise ValueError("min_company_price must be positive")

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
    known_companies = (
        frozenset(symbol.upper() for symbol in company_symbols)
        if company_symbols is not None
        else None
    )

    items: list[ResearchShortlistItem] = []
    excluded_partial = 0
    excluded_company_price = 0
    non_optionable_metadata = 0
    smart_money_matched = 0
    policy_matched = 0

    for classified in classifications:
        source = current_by_symbol.get(classified.symbol)
        if (
            source is None
            or source.signal != "BUY"
            or classified.status not in STOCK_PRIMARY_ACTIONABLE_STATUSES
        ):
            continue
        if source.partial_data:
            excluded_partial += 1
            continue
        if (
            known_companies is not None
            and source.symbol in known_companies
            and source.price < min_company_price
        ):
            excluded_company_price += 1
            continue
        if source.optionable is False:
            non_optionable_metadata += 1

        smart_bonus = smart_money_bonus(source.symbol, congressional, institutional)
        policy_bonus = trump_policy_bonus(source.symbol, trump_policy)
        if smart_bonus > 0:
            smart_money_matched += 1
        if policy_bonus > 0:
            policy_matched += 1
        stock_score = _stock_base_score(
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
                score=round(stock_score, 2),
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
        "company_min_price": min_company_price,
        "excluded_company_price_floor": excluded_company_price,
        "excluded_partial_data": excluded_partial,
        "non_optionable_metadata_count": non_optionable_metadata,
        "options_mode": "USER_DIRECTED_BROKER_CHAIN",
        "options_affect_stock_eligibility": False,
        "options_affect_stock_score": False,
        "stock_primary_execution": True,
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


def _stock_base_score(
    classified: ClassifiedRecord,
    source: OvtlyrRecord,
    sector_net_score: int,
) -> float:
    """Score stock evidence only; optionability cannot alter the result."""
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
