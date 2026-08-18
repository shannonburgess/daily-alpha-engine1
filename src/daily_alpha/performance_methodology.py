"""Fail-closed performance methodology contract for commercial-beta evidence.

This module defines calculation/evidence metadata only. It does not publish
performance, authorize customer claims, process payments, or enable trading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum


class PerformanceBasis(StrEnum):
    ACTUAL = "ACTUAL"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    HYPOTHETICAL = "HYPOTHETICAL"


class OptionMarkPolicy(StrEnum):
    OBSERVED_EXECUTABLE_SIDE = "OBSERVED_EXECUTABLE_SIDE"
    NO_OPTIONS = "NO_OPTIONS"


class QuoteQuality(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    STALE = "STALE"
    LOCKED = "LOCKED"
    CROSSED = "CROSSED"
    MISSING = "MISSING"


class CostEvidence(StrEnum):
    OBSERVED = "OBSERVED"
    ESTIMATED = "ESTIMATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class BenchmarkSpec:
    benchmark_id: str
    version: str
    frozen_at: str
    total_return: bool
    purpose: str

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.frozen_at)
        if not all((self.benchmark_id, self.version, self.purpose)):
            raise ValueError("benchmark identity, version, and purpose are required")


@dataclass(frozen=True)
class TransactionCostPolicy:
    version: str
    stock_commission_per_share: float
    stock_slippage_bps: float
    option_commission_per_contract: float
    option_entry_side: str = "ASK"
    option_exit_side: str = "BID"

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("transaction-cost version is required")
        if min(
            self.stock_commission_per_share,
            self.stock_slippage_bps,
            self.option_commission_per_contract,
        ) < 0:
            raise ValueError("transaction-cost assumptions cannot be negative")
        if self.option_entry_side != "ASK" or self.option_exit_side != "BID":
            raise ValueError("canonical long-option marks require ASK entry and BID exit")


@dataclass(frozen=True)
class PerformanceMethodology:
    version: str
    effective_at: str
    valuation_cutoff: str
    annualization_min_calendar_days: int
    benchmark: BenchmarkSpec
    cost_policy: TransactionCostPolicy
    option_mark_policy: OptionMarkPolicy
    point_in_time_universe_required: bool = True
    revised_data_may_overwrite_history: bool = False

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.effective_at)
        if not self.version or not self.valuation_cutoff:
            raise ValueError("methodology version and valuation cutoff are required")
        if self.annualization_min_calendar_days < 30:
            raise ValueError("annualization minimum must be at least 30 calendar days")
        if self.revised_data_may_overwrite_history:
            raise ValueError("revised data may not overwrite decision-time history")

    @property
    def methodology_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class PerformanceEvidence:
    evidence_id: str
    methodology_version: str
    performance_basis: PerformanceBasis
    strategy_version: str
    start_at: str
    end_at: str
    valuation_cutoff_at: str
    benchmark_id: str
    gross_return: float
    net_return: float
    cost_evidence: CostEvidence
    option_exposure: bool
    option_quote_quality: QuoteQuality | None
    source_cutoff_at: str
    evidence_hash: str

    def __post_init__(self) -> None:
        for value in (self.start_at, self.end_at, self.valuation_cutoff_at, self.source_cutoff_at):
            datetime.fromisoformat(value)
        if not all(
            (
                self.evidence_id,
                self.methodology_version,
                self.strategy_version,
                self.benchmark_id,
                self.evidence_hash,
            )
        ):
            raise ValueError("performance evidence identity and lineage are required")
        if len(self.evidence_hash) != 64:
            raise ValueError("evidence_hash must be a SHA-256 hex digest")
        if self.net_return > self.gross_return and self.cost_evidence != CostEvidence.NOT_APPLICABLE:
            raise ValueError("net return cannot exceed gross return when costs apply")


def validate_performance_evidence(
    methodology: PerformanceMethodology,
    evidence: tuple[PerformanceEvidence, ...],
) -> tuple[bool, tuple[str, ...]]:
    """Validate one customer-visible performance artifact fail-closed.

    A single artifact may contain multiple observations, but every observation
    must share the same performance basis and canonical methodology/benchmark.
    """

    reasons: list[str] = []
    if not evidence:
        return False, ("NO_PERFORMANCE_EVIDENCE",)

    bases = {item.performance_basis for item in evidence}
    if len(bases) != 1:
        reasons.append("MIXED_PERFORMANCE_BASES")

    if any(item.methodology_version != methodology.version for item in evidence):
        reasons.append("METHODOLOGY_VERSION_MISMATCH")

    if any(item.benchmark_id != methodology.benchmark.benchmark_id for item in evidence):
        reasons.append("BENCHMARK_MISMATCH")

    if methodology.option_mark_policy == OptionMarkPolicy.OBSERVED_EXECUTABLE_SIDE:
        for item in evidence:
            if item.option_exposure and item.option_quote_quality != QuoteQuality.EXECUTABLE:
                reasons.append("NON_EXECUTABLE_OPTION_MARK")
                break

    if any(item.cost_evidence == CostEvidence.ESTIMATED and item.net_return == item.gross_return for item in evidence):
        reasons.append("ESTIMATED_COSTS_NOT_REFLECTED_IN_NET_RETURN")

    return not reasons, tuple(reasons or ("PERFORMANCE_EVIDENCE_VALID",))
