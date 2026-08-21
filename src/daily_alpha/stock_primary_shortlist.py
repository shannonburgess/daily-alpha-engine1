"""Stock-primary actionable shortlist with optional ORATS research enrichment.

This module preserves the Daily Alpha stock model-validation contract:

* stock eligibility is determined before ORATS research enrichment;
* persistent ``ACTIVE_BUY`` names remain visible while the underlying BUY stays valid;
* OVTLYR optionability and ORATS availability/chain quality never remove or
  promote an otherwise eligible stock candidate;
* option research never changes the stock ranking score;
* company price/liquidity controls remain independent canonical gates; and
* emitted artifacts never authorize live trading.

The older :mod:`daily_alpha.research_shortlist` remains available for historical
research reproducibility. New actionable publication should use this module.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .config import OptionQualityRules
from .models import OptionCandidate
from .ovtlyr import (
    ClassifiedRecord,
    OvtlyrRecord,
    OvtlyrStatus,
    compare_universes,
    load_ovtlyr_csv,
    summarize_sector_rotation,
)
from .research_shortlist import (
    ResearchShortlistItem,
    ResearchShortlistResult,
    _best_qualified_option,
    _flow_contract,
    _most_unusual_option,
)
from .smart_money import (
    CongressionalAccumulation,
    InstitutionalAccumulation,
    smart_money_bonus,
)
from .sources import OratsBatchSource
from .trump_policy import TrumpPolicyCompany, trump_policy_bonus

STOCK_PRIMARY_ACTIONABLE_STATUSES = {
    OvtlyrStatus.NEW_BUY,
    OvtlyrStatus.EMERGING,
    OvtlyrStatus.LEADER,
    OvtlyrStatus.ENTRY_WATCH,
    OvtlyrStatus.RE_ENTRY,
    OvtlyrStatus.ACTIVE_BUY,
}

CANONICAL_COMPANY_MIN_PRICE = 10.0
_ORATS_NO_DTE_OPTIONS = "ORATS_NO_45_75_DTE_OPTIONS"


def build_stock_primary_shortlist(
    previous_path: str | Path,
    current_path: str | Path,
    *,
    as_of: datetime,
    orats_source: OratsBatchSource | None,
    request_limit: int = 20,
    option_rules: OptionQualityRules | None = None,
    congressional: tuple[CongressionalAccumulation, ...] = (),
    institutional: tuple[InstitutionalAccumulation, ...] = (),
    trump_policy: tuple[TrumpPolicyCompany, ...] = (),
    company_symbols: frozenset[str] | None = None,
    min_company_price: float = CANONICAL_COMPANY_MIN_PRICE,
) -> ResearchShortlistResult:
    """Build the stock-primary Daily Alpha shortlist.

    ``company_symbols`` should come from the same canonical liquidity evidence
    used to pre-filter the CSVs. When supplied, the $10 broad server-side price
    floor applies only to individual companies; ETF rows retain their separate
    liquidity/capacity treatment.

    ORATS is deliberately optional. A missing provider, provider exception,
    per-symbol error, missing 45-75 DTE contracts, poor option quality, or OVTLYR
    ``optionable=False`` changes only research metadata. It cannot remove a stock
    candidate and it cannot change the stock score.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if request_limit <= 0:
        raise ValueError("request_limit must be positive")
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

    staged: list[
        tuple[
            ClassifiedRecord,
            OvtlyrRecord,
            float,
            float,
            int | None,
            int | None,
            float,
            int | None,
        ]
    ] = []
    excluded_partial = 0
    excluded_company_price = 0
    research_non_optionable = 0
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
            research_non_optionable += 1

        base_score = _stock_base_score(
            classified,
            source,
            sector_scores.get(source.sector, 0),
        )
        smart_bonus = smart_money_bonus(source.symbol, congressional, institutional)
        policy_bonus = trump_policy_bonus(source.symbol, trump_policy)
        congress_rank = congressional_ranks.get(source.symbol.upper())
        institution_rank = institutional_ranks.get(source.symbol.upper())
        policy_rank = policy_ranks.get(source.symbol.upper())
        if smart_bonus > 0:
            smart_money_matched += 1
        if policy_bonus > 0:
            policy_matched += 1
        staged.append(
            (
                classified,
                source,
                base_score + smart_bonus + policy_bonus,
                smart_bonus,
                congress_rank,
                institution_rank,
                policy_bonus,
                policy_rank,
            )
        )

    # ORATS requests are research-only and quota-bounded. Known non-optionable
    # names remain in the stock shortlist but do not consume option-chain quota.
    staged.sort(key=lambda row: (-row[2], row[1].symbol))
    research_request_candidates = [
        row[1].symbol for row in staged if row[1].optionable is not False
    ]
    requested = tuple(research_request_candidates[:request_limit])
    requested_set = set(requested)

    chains: dict[str, Any] = {}
    errors: dict[str, str] = {}
    if orats_source is not None and requested:
        try:
            batch = orats_source.fetch(requested, as_of=as_of)
        except Exception as exc:  # noqa: BLE001 - optional research boundary
            provider_reason = f"ORATS_PROVIDER_{type(exc).__name__.upper()}"
            errors = {symbol: provider_reason for symbol in requested}
        else:
            chains = {chain.ticker: chain for chain in batch.chains}
            errors = dict(batch.errors)

    rules = option_rules or OptionQualityRules()
    items: list[ResearchShortlistItem] = []
    qualified_count = 0
    orats_data_error_count = 0
    orats_no_dte_count = 0
    unusual_call_company_count = 0
    unusual_put_company_count = 0

    for (
        classified,
        source,
        stock_score,
        smart_bonus,
        congress_rank,
        institution_rank,
        policy_bonus,
        policy_rank,
    ) in staged:
        symbol = source.symbol
        selected: OptionCandidate | None = None
        unusual_call: OptionCandidate | None = None
        unusual_put: OptionCandidate | None = None

        if source.optionable is False:
            orats_status = "RESEARCH_NOT_APPLICABLE"
            orats_reason = "OVTLYR_NOT_OPTIONABLE_STOCK_RETAINED"
            optionable = False
        elif orats_source is None:
            orats_status = "SOURCE_UNAVAILABLE"
            orats_reason = "ORATS_NOT_CONFIGURED_STOCK_RETAINED"
            optionable = source.optionable
        elif symbol not in requested_set:
            orats_status = "NOT_REQUESTED"
            orats_reason = "RESEARCH_API_LIMIT_STOCK_RETAINED"
            optionable = source.optionable
        elif symbol in errors:
            reason = errors[symbol]
            if reason == _ORATS_NO_DTE_OPTIONS:
                orats_no_dte_count += 1
                orats_status = "SOURCE_UNAVAILABLE"
                orats_reason = "ORATS_NO_45_75_DTE_OPTIONS_STOCK_RETAINED"
            else:
                orats_data_error_count += 1
                orats_status = "DATA_ERROR"
                orats_reason = f"{reason}_STOCK_RETAINED"
            optionable = source.optionable
        else:
            chain = chains.get(symbol)
            if chain is None:
                orats_data_error_count += 1
                orats_status = "DATA_ERROR"
                orats_reason = "ORATS_CHAIN_MISSING_STOCK_RETAINED"
                optionable = source.optionable
            else:
                optionable = True
                selected = _best_qualified_option(chain.candidates, rules)
                unusual_call = _most_unusual_option(chain.candidates, rules, "CALL")
                unusual_put = _most_unusual_option(chain.candidates, rules, "PUT")
                if unusual_call is not None:
                    unusual_call_company_count += 1
                if unusual_put is not None:
                    unusual_put_company_count += 1
                if selected is None:
                    orats_status = "ENRICHED"
                    orats_reason = "NO_OPTION_PASSED_QUALITY_FILTERS_STOCK_RETAINED"
                else:
                    qualified_count += 1
                    orats_status = "ENRICHED"
                    orats_reason = "QUALIFIED_OPTION_RESEARCH_ONLY"

        items.append(
            ResearchShortlistItem(
                symbol=symbol,
                ovtlyr_status=classified.status.value,
                display_label=classified.display_label,
                classification_reason=classified.reason,
                score=round(stock_score, 2),
                sector=source.sector,
                industry=source.industry,
                sector_net_score=sector_scores.get(source.sector, 0),
                trend=source.trend,
                momentum=source.momentum,
                optionable=optionable,
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
                selected_spread_pct=(
                    round(selected.spread_pct, 6) if selected else None
                ),
                selected_open_interest=selected.open_interest if selected else 0,
                selected_volume=selected.volume if selected else 0,
                unusual_options_activity=(
                    unusual_call is not None or unusual_put is not None
                ),
                unusual_call_contract=_flow_contract(unusual_call),
                unusual_call_volume=unusual_call.volume if unusual_call else 0,
                unusual_call_open_interest=(
                    unusual_call.open_interest if unusual_call else 0
                ),
                unusual_call_volume_oi_ratio=(
                    round(unusual_call.volume_to_open_interest, 6)
                    if unusual_call
                    else None
                ),
                unusual_call_bid=unusual_call.bid if unusual_call else 0.0,
                unusual_call_ask=unusual_call.ask if unusual_call else 0.0,
                unusual_put_contract=_flow_contract(unusual_put),
                unusual_put_volume=unusual_put.volume if unusual_put else 0,
                unusual_put_open_interest=(
                    unusual_put.open_interest if unusual_put else 0
                ),
                unusual_put_volume_oi_ratio=(
                    round(unusual_put.volume_to_open_interest, 6)
                    if unusual_put
                    else None
                ),
                unusual_put_bid=unusual_put.bid if unusual_put else 0.0,
                unusual_put_ask=unusual_put.ask if unusual_put else 0.0,
                smart_money_bonus=smart_bonus,
                congressional_rank=congress_rank,
                institutional_rank=institution_rank,
                trump_policy_bonus=policy_bonus,
                trump_policy_rank=policy_rank,
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
        # Legacy keys are retained for report compatibility but are always zero:
        # option research is no longer an actionable-stock exclusion.
        "excluded_not_optionable": 0,
        "excluded_orats_no_45_75_dte_options": 0,
        "research_non_optionable_count": research_non_optionable,
        "research_orats_no_45_75_dte_count": orats_no_dte_count,
        "orats_requests": len(requested) if orats_source is not None else 0,
        "orats_request_limit": request_limit,
        "qualified_option_count": qualified_count,
        "orats_data_error_count": orats_data_error_count,
        "unusual_call_company_count": unusual_call_company_count,
        "unusual_put_company_count": unusual_put_company_count,
        "unusual_activity_threshold_volume_oi": 1.0,
        "optionability_authority": "RESEARCH_ONLY_NON_BLOCKING",
        "orats_stock_eligibility_authority": False,
        "orats_changes_stock_score": False,
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
    """Score stock evidence only; optionability/ORATS are deliberately absent."""
    status_points = {
        OvtlyrStatus.EMERGING: 40,
        OvtlyrStatus.NEW_BUY: 36,
        OvtlyrStatus.RE_ENTRY: 34,
        OvtlyrStatus.ENTRY_WATCH: 30,
        OvtlyrStatus.LEADER: 26,
        OvtlyrStatus.ACTIVE_BUY: 20,
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
