"""Quota-aware ORATS enrichment for prequalified ranked candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .orats import OratsChain
from .sources import OratsBatchSource


class EnrichmentStatus(StrEnum):
    ENRICHED = "ENRICHED"
    DATA_ERROR = "DATA_ERROR"
    NOT_REQUESTED = "NOT_REQUESTED"


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    score: float
    pine_entry: bool
    risk_approved: bool

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("candidate symbol is required")


@dataclass(frozen=True)
class EnrichedCandidate:
    candidate: RankedCandidate
    status: EnrichmentStatus
    reason: str
    chain: OratsChain | None = None


@dataclass(frozen=True)
class ShortlistResult:
    candidates: tuple[EnrichedCandidate, ...]
    api_requests: int
    request_limit: int

    @property
    def has_data_errors(self) -> bool:
        return any(
            item.status == EnrichmentStatus.DATA_ERROR for item in self.candidates
        )


class OratsShortlistEnricher:
    def __init__(self, source: OratsBatchSource, *, request_limit: int = 20) -> None:
        if request_limit <= 0:
            raise ValueError("request_limit must be positive")
        self.source = source
        self.request_limit = request_limit

    def enrich(
        self,
        candidates: tuple[RankedCandidate, ...],
        *,
        as_of: datetime,
    ) -> ShortlistResult:
        eligible = sorted(
            (item for item in candidates if item.pine_entry and item.risk_approved),
            key=lambda item: (-item.score, item.symbol.upper()),
        )
        requested = tuple(
            item.symbol.upper() for item in eligible[: self.request_limit]
        )
        batch = self.source.fetch(requested, as_of=as_of)
        chains = {chain.ticker: chain for chain in batch.chains}
        errors = dict(batch.errors)
        requested_set = set(requested)

        enriched: list[EnrichedCandidate] = []
        for candidate in candidates:
            symbol = candidate.symbol.upper()
            if not candidate.pine_entry:
                enriched.append(
                    EnrichedCandidate(
                        candidate, EnrichmentStatus.NOT_REQUESTED, "PINE_GATE_FAILED"
                    )
                )
            elif not candidate.risk_approved:
                enriched.append(
                    EnrichedCandidate(
                        candidate, EnrichmentStatus.NOT_REQUESTED, "RISK_GATE_FAILED"
                    )
                )
            elif symbol not in requested_set:
                enriched.append(
                    EnrichedCandidate(
                        candidate, EnrichmentStatus.NOT_REQUESTED, "API_LIMIT_REACHED"
                    )
                )
            elif symbol in errors:
                enriched.append(
                    EnrichedCandidate(
                        candidate, EnrichmentStatus.DATA_ERROR, errors[symbol]
                    )
                )
            else:
                enriched.append(
                    EnrichedCandidate(
                        candidate,
                        EnrichmentStatus.ENRICHED,
                        "ORATS_CHAIN_VALID",
                        chains[symbol],
                    )
                )
        return ShortlistResult(tuple(enriched), len(requested), self.request_limit)
