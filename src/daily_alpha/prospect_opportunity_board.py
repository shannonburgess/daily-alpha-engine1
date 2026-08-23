"""Prospect/subscriber opportunity presentation without arbitrary Top-N truncation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime

from .candidates import CandidateAssessment, CandidateBucket, rank_candidates

TOP_PICK_LIMIT = 3
QUALIFYING_BUCKETS = frozenset(
    {
        CandidateBucket.OPTION_SETUP,
        CandidateBucket.STOCK_FALLBACK,
        CandidateBucket.ENTRY_WATCH,
    }
)
SIGNAL_CONTEXT = "GOVERNED_RESEARCH_MODEL_SIGNAL_NOT_PERSONALIZED_ADVICE"


class ProspectOpportunityBoardError(ValueError):
    """Prospect opportunity board input violates V1 presentation invariants."""


@dataclass(frozen=True, slots=True)
class ProspectOpportunity:
    rank: int
    candidate_id: str
    symbol: str
    lifecycle_status: str
    bucket: str
    score: float
    sector: str
    sector_net_score: int
    instrument_selected: str
    fallback_reason: str
    pine_entry: bool
    risk_gate_passed: bool
    optionable: bool | None
    selected_expiration: str
    selected_strike: float
    selected_delta: float | None
    selected_spread_pct: float | None
    unusual_options_activity: bool
    confidence: float | None = None
    thesis: str = ""
    evidence_lineage: tuple[str, ...] = ()
    industry: str = ""
    theme: str = ""
    trend: str = ""
    momentum: str = ""
    price: float | None = None
    average_volume: float | None = None
    average_daily_dollar_volume: float | None = None
    catalyst_context: tuple[str, ...] = ()
    risk_context: tuple[str, ...] = ()
    invalidation: str = ""

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ProspectOpportunityBoardError("OPPORTUNITY_RANK_MUST_BE_POSITIVE")
        if not self.candidate_id.strip():
            raise ProspectOpportunityBoardError("CANDIDATE_ID_REQUIRED")
        if not self.symbol.strip():
            raise ProspectOpportunityBoardError("SYMBOL_REQUIRED")
        if self.bucket not in {item.value for item in QUALIFYING_BUCKETS}:
            raise ProspectOpportunityBoardError("NON_QUALIFYING_BUCKET_IN_OPPORTUNITY_BOARD")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FilteredProspectCandidate:
    candidate_id: str
    symbol: str
    lifecycle_status: str
    bucket: str
    score: float
    reason: str
    thesis: str = ""
    evidence_lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ProspectOpportunityBoardError("FILTERED_CANDIDATE_ID_REQUIRED")
        if not self.symbol.strip():
            raise ProspectOpportunityBoardError("FILTERED_SYMBOL_REQUIRED")
        if not self.reason.strip():
            raise ProspectOpportunityBoardError("FILTERED_REASON_REQUIRED")
        if self.bucket in {item.value for item in QUALIFYING_BUCKETS}:
            raise ProspectOpportunityBoardError("QUALIFYING_CANDIDATE_CANNOT_BE_FILTERED")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OpportunityBoardFilter:
    """Deterministic query over the canonical qualifying set; never a discovery gate."""

    symbols: tuple[str, ...] = ()
    lifecycle_statuses: tuple[str, ...] = ()
    buckets: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    instrument_selected: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _normalize_filter_values(self.symbols, "SYMBOL"))
        object.__setattr__(
            self,
            "lifecycle_statuses",
            _normalize_filter_values(self.lifecycle_statuses, "LIFECYCLE_STATUS"),
        )
        object.__setattr__(self, "buckets", _normalize_filter_values(self.buckets, "BUCKET"))
        object.__setattr__(self, "sectors", _normalize_filter_values(self.sectors, "SECTOR"))
        object.__setattr__(self, "themes", _normalize_filter_values(self.themes, "THEME"))
        object.__setattr__(
            self,
            "instrument_selected",
            _normalize_filter_values(self.instrument_selected, "INSTRUMENT_SELECTED"),
        )
        qualifying_bucket_values = {item.value.upper() for item in QUALIFYING_BUCKETS}
        if any(bucket not in qualifying_bucket_values for bucket in self.buckets):
            raise ProspectOpportunityBoardError("FILTER_BUCKET_NOT_QUALIFYING")

    @property
    def filter_id(self) -> str:
        return _sha(self.to_dict())

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.symbols,
                self.lifecycle_statuses,
                self.buckets,
                self.sectors,
                self.themes,
                self.instrument_selected,
            )
        )

    def matches(self, opportunity: ProspectOpportunity) -> bool:
        checks = (
            (self.symbols, opportunity.symbol),
            (self.lifecycle_statuses, opportunity.lifecycle_status),
            (self.buckets, opportunity.bucket),
            (self.sectors, opportunity.sector),
            (self.themes, opportunity.theme),
            (self.instrument_selected, opportunity.instrument_selected),
        )
        return all(not allowed or value.strip().upper() in allowed for allowed, value in checks)

    def to_dict(self) -> dict[str, tuple[str, ...]]:
        return {
            "symbols": self.symbols,
            "lifecycle_statuses": self.lifecycle_statuses,
            "buckets": self.buckets,
            "sectors": self.sectors,
            "themes": self.themes,
            "instrument_selected": self.instrument_selected,
        }


@dataclass(frozen=True, slots=True)
class OpportunityBoardPage:
    board_id: str
    filter_id: str
    offset: int
    limit: int
    total_qualifying: int
    total_matched: int
    opportunities: tuple[ProspectOpportunity, ...]
    has_more: bool

    def __post_init__(self) -> None:
        if not self.board_id.strip():
            raise ProspectOpportunityBoardError("PAGE_BOARD_ID_REQUIRED")
        if not self.filter_id.strip():
            raise ProspectOpportunityBoardError("PAGE_FILTER_ID_REQUIRED")
        if self.offset < 0:
            raise ProspectOpportunityBoardError("PAGE_OFFSET_MUST_BE_NON_NEGATIVE")
        if self.limit < 1:
            raise ProspectOpportunityBoardError("PAGE_LIMIT_MUST_BE_POSITIVE")
        if self.total_qualifying < self.total_matched:
            raise ProspectOpportunityBoardError("PAGE_MATCHED_TOTAL_EXCEEDS_CANONICAL_TOTAL")
        if self.total_matched < len(self.opportunities):
            raise ProspectOpportunityBoardError("PAGE_MATCHED_TOTAL_CANNOT_BE_SMALLER_THAN_PAGE")

    def to_dict(self) -> dict[str, object]:
        return {
            "board_id": self.board_id,
            "filter_id": self.filter_id,
            "offset": self.offset,
            "limit": self.limit,
            "total_qualifying": self.total_qualifying,
            "total_matched": self.total_matched,
            "opportunities": [item.to_dict() for item in self.opportunities],
            "has_more": self.has_more,
        }


@dataclass(frozen=True, slots=True)
class ProspectOpportunityBoard:
    as_of: datetime
    source_revision: str
    opportunities: tuple[ProspectOpportunity, ...]
    filtered: tuple[FilteredProspectCandidate, ...]
    signal_context: str = SIGNAL_CONTEXT
    prospect_ready: bool = True
    portfolio_recommendation_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.as_of)
        if not self.source_revision.strip():
            raise ProspectOpportunityBoardError("SOURCE_REVISION_REQUIRED")
        if self.signal_context != SIGNAL_CONTEXT:
            raise ProspectOpportunityBoardError("INVALID_SIGNAL_CONTEXT")
        if any(
            (
                self.portfolio_recommendation_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ProspectOpportunityBoardError("PROSPECT_BOARD_CANNOT_GRANT_EXECUTION_AUTHORITY")

        expected_ranks = tuple(range(1, len(self.opportunities) + 1))
        actual_ranks = tuple(item.rank for item in self.opportunities)
        if actual_ranks != expected_ranks:
            raise ProspectOpportunityBoardError("OPPORTUNITY_RANKS_MUST_BE_CONTIGUOUS")

        opportunity_ids = tuple(item.candidate_id for item in self.opportunities)
        filtered_ids = tuple(item.candidate_id for item in self.filtered)
        if len(set(opportunity_ids)) != len(opportunity_ids):
            raise ProspectOpportunityBoardError("DUPLICATE_QUALIFYING_CANDIDATE_ID")
        if len(set(filtered_ids)) != len(filtered_ids):
            raise ProspectOpportunityBoardError("DUPLICATE_FILTERED_CANDIDATE_ID")
        if set(opportunity_ids) & set(filtered_ids):
            raise ProspectOpportunityBoardError("CANDIDATE_CANNOT_BE_QUALIFIED_AND_FILTERED")

        symbols = tuple(item.symbol for item in self.opportunities) + tuple(
            item.symbol for item in self.filtered
        )
        if len(set(symbols)) != len(symbols):
            raise ProspectOpportunityBoardError("DUPLICATE_SYMBOL_IN_PROSPECT_SNAPSHOT")

    @property
    def board_id(self) -> str:
        return _sha(
            {
                "as_of": self.as_of.isoformat(),
                "source_revision": self.source_revision,
                "opportunity_ids": tuple(item.candidate_id for item in self.opportunities),
                "filtered_ids": tuple(item.candidate_id for item in self.filtered),
                "signal_context": self.signal_context,
            }
        )

    @property
    def total_qualifying(self) -> int:
        return len(self.opportunities)

    @property
    def top_picks(self) -> tuple[ProspectOpportunity, ...]:
        return self.opportunities[:TOP_PICK_LIMIT]

    @property
    def additional_opportunities(self) -> tuple[ProspectOpportunity, ...]:
        return self.opportunities[TOP_PICK_LIMIT:]

    def page(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        query: OpportunityBoardFilter | None = None,
    ) -> OpportunityBoardPage:
        """Return a bounded query view while preserving the complete canonical board identity."""
        if offset < 0:
            raise ProspectOpportunityBoardError("PAGE_OFFSET_MUST_BE_NON_NEGATIVE")
        if limit < 1:
            raise ProspectOpportunityBoardError("PAGE_LIMIT_MUST_BE_POSITIVE")
        effective_query = query or OpportunityBoardFilter()
        matched = tuple(item for item in self.opportunities if effective_query.matches(item))
        page_items = matched[offset : offset + limit]
        return OpportunityBoardPage(
            board_id=self.board_id,
            filter_id=effective_query.filter_id,
            offset=offset,
            limit=limit,
            total_qualifying=self.total_qualifying,
            total_matched=len(matched),
            opportunities=page_items,
            has_more=offset + len(page_items) < len(matched),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "board_id": self.board_id,
            "as_of": self.as_of.isoformat(),
            "source_revision": self.source_revision,
            "signal_context": self.signal_context,
            "total_qualifying": self.total_qualifying,
            "top_picks": [item.to_dict() for item in self.top_picks],
            "additional_opportunities": [
                item.to_dict() for item in self.additional_opportunities
            ],
            "full_qualified_opportunity_board": [
                item.to_dict() for item in self.opportunities
            ],
            "filtered": [item.to_dict() for item in self.filtered],
            "prospect_ready": self.prospect_ready,
            "portfolio_recommendation_authorized": self.portfolio_recommendation_authorized,
            "paper_mutation_authorized": self.paper_mutation_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


def build_prospect_opportunity_board(
    *,
    items: tuple[CandidateAssessment, ...],
    as_of: datetime,
    source_revision: str,
) -> ProspectOpportunityBoard:
    """Build the V1 Top-3 presentation and complete canonical qualifying board."""
    _require_aware(as_of)
    if not source_revision.strip():
        raise ProspectOpportunityBoardError("SOURCE_REVISION_REQUIRED")

    ranked = rank_candidates(items)
    seen_symbols: set[str] = set()
    opportunities: list[ProspectOpportunity] = []
    filtered: list[FilteredProspectCandidate] = []

    for candidate in ranked:
        symbol = candidate.symbol.strip().upper()
        if not symbol:
            raise ProspectOpportunityBoardError("SYMBOL_REQUIRED")
        if symbol in seen_symbols:
            raise ProspectOpportunityBoardError("DUPLICATE_SYMBOL_IN_PROSPECT_SNAPSHOT")
        seen_symbols.add(symbol)

        candidate_id = _candidate_id(candidate, as_of=as_of, source_revision=source_revision)
        if candidate.bucket in QUALIFYING_BUCKETS:
            opportunities.append(
                ProspectOpportunity(
                    rank=len(opportunities) + 1,
                    candidate_id=candidate_id,
                    symbol=symbol,
                    lifecycle_status=candidate.ovtlyr_status,
                    bucket=candidate.bucket.value,
                    score=candidate.score,
                    sector=candidate.sector,
                    sector_net_score=candidate.sector_net_score,
                    instrument_selected=candidate.instrument_selected,
                    fallback_reason=candidate.fallback_reason,
                    pine_entry=candidate.pine_entry,
                    risk_gate_passed=candidate.risk_gate_passed,
                    optionable=candidate.optionable,
                    selected_expiration=candidate.selected_expiration,
                    selected_strike=candidate.selected_strike,
                    selected_delta=candidate.selected_delta,
                    selected_spread_pct=candidate.selected_spread_pct,
                    unusual_options_activity=candidate.unusual_options_activity,
                    confidence=candidate.confidence,
                    thesis=candidate.classification_reason,
                    evidence_lineage=(source_revision,),
                    industry=candidate.industry,
                    theme=candidate.theme or candidate.industry,
                    trend=candidate.trend,
                    momentum=candidate.momentum,
                    price=candidate.price,
                    average_volume=candidate.average_volume,
                    average_daily_dollar_volume=_dollar_volume(candidate),
                    catalyst_context=candidate.catalyst_context,
                    risk_context=candidate.risk_context,
                    invalidation=candidate.invalidation,
                )
            )
        else:
            filtered.append(
                FilteredProspectCandidate(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    lifecycle_status=candidate.ovtlyr_status,
                    bucket=candidate.bucket.value,
                    score=candidate.score,
                    reason=_filtered_reason(candidate),
                    thesis=candidate.classification_reason,
                    evidence_lineage=(source_revision,),
                )
            )

    return ProspectOpportunityBoard(
        as_of=as_of,
        source_revision=source_revision,
        opportunities=tuple(opportunities),
        filtered=tuple(filtered),
    )


def _candidate_id(
    candidate: CandidateAssessment,
    *,
    as_of: datetime,
    source_revision: str,
) -> str:
    return _sha(
        {
            "as_of": as_of.isoformat(),
            "source_revision": source_revision,
            "candidate": candidate.to_dict(),
        }
    )


def _dollar_volume(candidate: CandidateAssessment) -> float | None:
    if candidate.price is None or candidate.average_volume is None:
        return None
    if candidate.price <= 0 or candidate.average_volume <= 0:
        return None
    return candidate.price * candidate.average_volume


def _filtered_reason(candidate: CandidateAssessment) -> str:
    reason = candidate.fallback_reason.strip()
    if reason:
        return reason
    if candidate.bucket is CandidateBucket.DATA_ERROR:
        return "DATA_ERROR"
    return "NOT_CURRENTLY_QUALIFIED"


def _normalize_filter_values(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            raise ProspectOpportunityBoardError(f"FILTER_{field}_VALUE_REQUIRED")
        normalized.append(cleaned.upper())
    return tuple(sorted(set(normalized)))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectOpportunityBoardError("AS_OF_MUST_BE_TIMEZONE_AWARE")


def _sha(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "QUALIFYING_BUCKETS",
    "SIGNAL_CONTEXT",
    "TOP_PICK_LIMIT",
    "FilteredProspectCandidate",
    "OpportunityBoardFilter",
    "OpportunityBoardPage",
    "ProspectOpportunity",
    "ProspectOpportunityBoard",
    "ProspectOpportunityBoardError",
    "build_prospect_opportunity_board",
]
