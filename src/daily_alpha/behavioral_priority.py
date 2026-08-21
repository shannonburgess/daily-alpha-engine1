"""Research-priority overlay for Behavioral Change evidence.

Behavioral / Information Edge may reorder research attention only. This module is an
explicit isolation boundary: it never authorizes execution and it never changes the
state of canonical signal, earnings/event, liquidity, concentration, or portfolio-risk
gates. Under the stock-primary PAPER policy, ORATS/options are research metadata only
and are deliberately excluded from the required execution-gate set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .behavioral_factors import BehavioralResearchFactors


class CoreExecutionGate(StrEnum):
    PINE = "PINE"
    EARNINGS = "EARNINGS"
    LIQUIDITY = "LIQUIDITY"
    CONCENTRATION = "CONCENTRATION"
    PORTFOLIO_RISK = "PORTFOLIO_RISK"


class CoreGateState(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    DATA_ERROR = "DATA_ERROR"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class CoreGateEvidence:
    gate: CoreExecutionGate
    state: CoreGateState
    reason: str = ""

    @property
    def blocking(self) -> bool:
        return self.state != CoreGateState.PASS


@dataclass(frozen=True)
class BehavioralResearchPriorityOverlay:
    ticker: str
    as_of: datetime
    base_research_priority: float
    requested_adjustment: float
    applied_adjustment: float
    research_priority: float
    status: str
    reason: str
    core_gates: tuple[CoreGateEvidence, ...]
    blocking_core_gates: tuple[str, ...]
    core_execution_gates_all_pass: bool
    execution_gate_override: bool = False
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def apply_behavioral_research_priority(
    *,
    ticker: str,
    as_of: datetime,
    base_research_priority: float,
    requested_adjustment: float,
    max_abs_adjustment: float,
    factors: BehavioralResearchFactors,
    core_gates: tuple[CoreGateEvidence, ...],
) -> BehavioralResearchPriorityOverlay:
    """Apply a bounded Behavioral adjustment to research priority only.

    The caller owns the research hypothesis that produced ``requested_adjustment``.
    This boundary only applies a configured cap after confirming that the canonical
    multi-source Behavioral score exists. Canonical execution-gate evidence is carried
    through unchanged for auditability and can never be converted to PASS here. ORATS
    is intentionally absent because it cannot block a new STOCK PAPER entry.
    """
    _require_aware(as_of, "as_of")
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker is required")
    for name, value in (
        ("base_research_priority", base_research_priority),
        ("requested_adjustment", requested_adjustment),
        ("max_abs_adjustment", max_abs_adjustment),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not 0.0 <= base_research_priority <= 100.0:
        raise ValueError("base_research_priority must be in [0, 100]")
    if max_abs_adjustment < 0.0:
        raise ValueError("max_abs_adjustment must be non-negative")

    _validate_factor_safety(factors)
    ordered_gates = _validate_core_gates(core_gates)
    blocking = tuple(row.gate.value for row in ordered_gates if row.blocking)

    if factors.behavioral_change_score is None:
        applied = 0.0
        status = "NO_PRIORITY_ADJUSTMENT"
        reason = "BEHAVIORAL_CHANGE_SCORE_UNAVAILABLE"
    else:
        applied = max(-max_abs_adjustment, min(max_abs_adjustment, requested_adjustment))
        status = "RESEARCH_PRIORITY_ADJUSTED" if applied != 0.0 else "NO_PRIORITY_ADJUSTMENT"
        reason = ""

    priority = max(0.0, min(100.0, base_research_priority + applied))
    return BehavioralResearchPriorityOverlay(
        ticker=symbol,
        as_of=as_of.astimezone(UTC),
        base_research_priority=round(base_research_priority, 6),
        requested_adjustment=round(requested_adjustment, 6),
        applied_adjustment=round(applied, 6),
        research_priority=round(priority, 6),
        status=status,
        reason=reason,
        core_gates=ordered_gates,
        blocking_core_gates=blocking,
        core_execution_gates_all_pass=not blocking,
    )


def _validate_factor_safety(factors: BehavioralResearchFactors) -> None:
    if factors.research_only is not True:
        raise ValueError("BEHAVIORAL_PRIORITY_RESEARCH_ONLY_REQUIRED")
    if factors.trading_authorized is not False:
        raise ValueError("BEHAVIORAL_PRIORITY_TRADING_AUTHORIZATION_REJECTED")
    if factors.live_trading_enabled is not False:
        raise ValueError("BEHAVIORAL_PRIORITY_LIVE_TRADING_REJECTED")


def _validate_core_gates(
    rows: tuple[CoreGateEvidence, ...],
) -> tuple[CoreGateEvidence, ...]:
    by_gate: dict[CoreExecutionGate, CoreGateEvidence] = {}
    for row in rows:
        prior = by_gate.get(row.gate)
        if prior is not None and prior != row:
            raise ValueError("CONFLICTING_DUPLICATE_CORE_EXECUTION_GATE")
        by_gate[row.gate] = row
    expected = set(CoreExecutionGate)
    observed = set(by_gate)
    if observed != expected:
        missing = ",".join(sorted(gate.value for gate in expected - observed))
        extra = ",".join(sorted(gate.value for gate in observed - expected))
        detail = f"missing={missing};extra={extra}"
        raise ValueError(f"INCOMPLETE_CORE_EXECUTION_GATE_SET:{detail}")
    return tuple(by_gate[gate] for gate in CoreExecutionGate)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
