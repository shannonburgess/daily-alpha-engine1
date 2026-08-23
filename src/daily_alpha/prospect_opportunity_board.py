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
class OpportunityBoardPage:
    board_id: str
    offset: int
    limit: int
    total_qualifying: int
    opportunities: tuple[ProspectOpportunity, ...]
    has_more: bool

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ProspectOpportunityBoardError("PAGE_OFFSET_MUST_BE_NON_NEGATIVE")
        if self.limit < 1:
            raise ProspectOpportunityBoardError("PAGE_LIMIT_MUST_BE_POSITIVE")
        if self.total_qualifying < len(self.opportunities):
            raise ProspectOpportunityBoardError("PAGE_TOTAL_CANNOT_BE_SMALLER_THAN_PAGE")


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

    def page(self, *, offset: int = 0, limit: int = 50) -> OpportunityBoardPage:
        if offset < 0:
            raise ProspectOpportunityBoardError("PAGE_OFFSET_MUST_BE_NON_NEGATIVE")
        if limit < 1:
            raise ProspectOpportunityBoardError("PAGE_LIMIT_MUST_BE_POSITIVE")
        page_items = self.opportunities[offset : offset + limit]
        return OpportunityBoardPage(
            board_id=self.board_id,
            offset=offset,
            limit=limit,
            total_qualifying=self.total_qualifying,
            opportunities=page_items,
            has_more=offset + len(page_items) < self.total_qualifying,
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


def _filtered_reason(candidate: CandidateAssessment) -> str:
    reason = candidate.fallback_reason.strip()
    if reason:
        return reason
    if candidate.bucket is CandidateBucket.DATA_ERROR:
        return "DATA_ERROR"
    return "NOT_CURRENTLY_QUALIFIED"


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectOpportunityBoardError("AS_OF_MUST_BE_TIMEZONE_AWARE")


def _sha(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FilteredProspectCandidate",
    "OpportunityBoardPage",
    "ProspectOpportunity",
    "ProspectOpportunityBoard",
    "ProspectOpportunityBoardError",
    "QUALIFYING_BUCKETS",
    "SIGNAL_CONTEXT",
    "TOP_PICK_LIMIT",
    "build_prospect_opportunity_board",
]
