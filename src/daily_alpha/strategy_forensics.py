"""Research-only strategy forensics and missed-R diagnostics.

This module measures what happened after a Daily Alpha decision so the platform can
find systematic missed winners, weak filters, early exits, and model disagreement.
It consumes already-known decision/path observations and never authorizes a trade.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OpportunityPath:
    symbol: str
    strategy_version: str
    decision: str
    reason: str
    reference_price: float
    stop_price: float
    max_price_after: float
    min_price_after: float
    terminal_price: float
    bars_observed: int
    executed: bool = False
    exit_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ForensicsDiagnostic:
    symbol: str
    strategy_version: str
    decision: str
    reason: str
    executed: bool
    initial_risk_per_share: float
    mfe_r: float
    mae_r: float
    terminal_r: float
    realized_r: float | None
    mfe_capture_pct: float | None
    missed_r: float
    classification: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelDisagreement:
    symbol: str
    champion_version: str
    challenger_version: str
    champion_decision: str
    challenger_decision: str
    champion_reason: str
    challenger_reason: str
    disagrees: bool
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def diagnose_opportunity(
    path: OpportunityPath,
    *,
    missed_winner_threshold_r: float = 2.0,
    early_exit_remaining_r: float = 1.0,
) -> ForensicsDiagnostic:
    """Measure one decision path in R without hindsight-changing the decision."""
    if missed_winner_threshold_r <= 0 or early_exit_remaining_r <= 0:
        raise ValueError("FORENSICS_THRESHOLDS_MUST_BE_POSITIVE")
    _validate_path(path)

    risk = path.reference_price - path.stop_price
    mfe_r = (path.max_price_after - path.reference_price) / risk
    mae_r = (path.min_price_after - path.reference_price) / risk
    terminal_r = (path.terminal_price - path.reference_price) / risk
    realized_r = None
    capture_pct = None
    missed_r = max(0.0, mfe_r)

    if path.executed:
        if path.exit_price is None:
            classification = "OPEN_EXECUTED_PATH"
            missed_r = max(0.0, mfe_r)
        else:
            realized_r = (path.exit_price - path.reference_price) / risk
            missed_r = max(0.0, mfe_r - realized_r)
            if mfe_r > 0:
                capture_pct = max(0.0, min(1.0, realized_r / mfe_r)) * 100.0
            remaining_after_exit_r = (path.max_price_after - path.exit_price) / risk
            if remaining_after_exit_r >= early_exit_remaining_r:
                classification = "EARLY_EXIT_MISSED_RUNNER"
            elif realized_r <= -1.0:
                classification = "STOPPED_OR_FAILED_SETUP"
            elif realized_r > 0:
                classification = "PROFIT_CAPTURED"
            else:
                classification = "FLAT_OR_SMALL_LOSS_EXIT"
    elif mfe_r >= missed_winner_threshold_r:
        classification = "MISSED_WINNER"
    elif mfe_r >= 1.0:
        classification = "MISSED_POSITIVE_ASYMMETRY"
    elif mae_r <= -1.0:
        classification = "CORRECTLY_AVOIDED_OR_FAILED"
    else:
        classification = "INCONCLUSIVE_WAIT"

    return ForensicsDiagnostic(
        symbol=path.symbol.upper(),
        strategy_version=path.strategy_version,
        decision=path.decision.upper(),
        reason=path.reason,
        executed=path.executed,
        initial_risk_per_share=round(risk, 8),
        mfe_r=round(mfe_r, 6),
        mae_r=round(mae_r, 6),
        terminal_r=round(terminal_r, 6),
        realized_r=None if realized_r is None else round(realized_r, 6),
        mfe_capture_pct=None if capture_pct is None else round(capture_pct, 2),
        missed_r=round(missed_r, 6),
        classification=classification,
    )


def summarize_forensics(
    diagnostics: list[ForensicsDiagnostic],
) -> dict[str, Any]:
    """Aggregate missed opportunity by reason without hiding low sample sizes."""
    by_reason: dict[str, list[ForensicsDiagnostic]] = defaultdict(list)
    for item in diagnostics:
        by_reason[item.reason or "UNSPECIFIED"].append(item)

    reason_rows = []
    for reason, items in sorted(by_reason.items()):
        missed = [item for item in items if item.classification == "MISSED_WINNER"]
        early = [
            item
            for item in items
            if item.classification == "EARLY_EXIT_MISSED_RUNNER"
        ]
        captures = [
            item.mfe_capture_pct
            for item in items
            if item.mfe_capture_pct is not None
        ]
        reason_rows.append(
            {
                "reason": reason,
                "observations": len(items),
                "missed_winners": len(missed),
                "early_exit_missed_runners": len(early),
                "mean_mfe_r": _mean([item.mfe_r for item in items]),
                "mean_missed_r": _mean([item.missed_r for item in items]),
                "mean_mfe_capture_pct": _mean(captures),
            }
        )

    return {
        "observations": len(diagnostics),
        "missed_winner_count": sum(
            item.classification == "MISSED_WINNER" for item in diagnostics
        ),
        "early_exit_missed_runner_count": sum(
            item.classification == "EARLY_EXIT_MISSED_RUNNER"
            for item in diagnostics
        ),
        "mean_missed_r": _mean([item.missed_r for item in diagnostics]),
        "by_reason": reason_rows,
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def compare_model_decisions(
    *,
    symbol: str,
    champion_version: str,
    challenger_version: str,
    champion_decision: str,
    challenger_decision: str,
    champion_reason: str = "",
    challenger_reason: str = "",
) -> ModelDisagreement:
    """Create one auditable champion/challenger disagreement observation."""
    champion = champion_decision.strip().upper()
    challenger = challenger_decision.strip().upper()
    if not symbol.strip() or not champion or not challenger:
        raise ValueError("MODEL_DISAGREEMENT_FIELDS_REQUIRED")
    return ModelDisagreement(
        symbol=symbol.upper(),
        champion_version=champion_version,
        challenger_version=challenger_version,
        champion_decision=champion,
        challenger_decision=challenger,
        champion_reason=champion_reason,
        challenger_reason=challenger_reason,
        disagrees=champion != challenger or champion_reason != challenger_reason,
    )


def _validate_path(path: OpportunityPath) -> None:
    if not path.symbol.strip() or not path.strategy_version.strip():
        raise ValueError("FORENSICS_IDENTITY_REQUIRED")
    if path.reference_price <= 0 or path.stop_price <= 0:
        raise ValueError("FORENSICS_PRICES_MUST_BE_POSITIVE")
    if path.stop_price >= path.reference_price:
        raise ValueError("FORENSICS_STOP_MUST_BE_BELOW_REFERENCE")
    if path.max_price_after <= 0 or path.min_price_after <= 0 or path.terminal_price <= 0:
        raise ValueError("FORENSICS_PATH_PRICES_MUST_BE_POSITIVE")
    if path.max_price_after < path.min_price_after:
        raise ValueError("FORENSICS_PATH_RANGE_INVALID")
    if path.bars_observed <= 0:
        raise ValueError("FORENSICS_BARS_OBSERVED_INVALID")
    if path.executed and path.exit_price is not None and path.exit_price <= 0:
        raise ValueError("FORENSICS_EXIT_PRICE_INVALID")
    if not path.executed and path.exit_price is not None:
        raise ValueError("FORENSICS_NONEXECUTED_EXIT_INVALID")


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)
