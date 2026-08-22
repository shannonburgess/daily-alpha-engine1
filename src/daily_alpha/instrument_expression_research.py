"""Research-only instrument-expression hierarchy for Daily Alpha.

This module deliberately has no execution dependency. It separates alpha selection
from the instrument used to express that alpha and preserves fail-closed behavior
when required data is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Expression(str, Enum):
    """Research classification for how a validated signal could be expressed."""

    SHARES = "SHARES"
    SHARES_PLUS_LONG_CALL = "SHARES_PLUS_LONG_CALL"
    SECTOR_2X = "SECTOR_2X"
    SECTOR_3X = "SECTOR_3X"
    NO_TRADE = "NO_TRADE"


class SectorStrength(str, Enum):
    """Precomputed sector state supplied by a point-in-time research caller."""

    NONE = "NONE"
    STRONG = "STRONG"
    EXCEPTIONAL = "EXCEPTIONAL"


@dataclass(frozen=True)
class ExpressionPolicy:
    """Pre-registered research gates; not paper/live configuration."""

    min_long_call_dte: int = 90
    max_long_call_dte: int = 150
    allow_3x_sector_research: bool = False

    def __post_init__(self) -> None:
        if self.min_long_call_dte <= 0:
            raise ValueError("min_long_call_dte must be positive")
        if self.max_long_call_dte < self.min_long_call_dte:
            raise ValueError("max_long_call_dte must be >= min_long_call_dte")


@dataclass(frozen=True)
class ExpressionInputs:
    """Point-in-time research state used by the disconnected classifier."""

    individual_r2_qualified: bool
    required_data_ok: bool = True
    option_quality_ok: bool = False
    option_dte: int | None = None
    sector_strength: SectorStrength = SectorStrength.NONE
    sector_breadth_ok: bool = False


@dataclass(frozen=True)
class ExpressionDecision:
    expression: Expression
    reason: str
    option_overlay_eligible: bool = False


def classify_expression(
    inputs: ExpressionInputs,
    policy: ExpressionPolicy | None = None,
) -> ExpressionDecision:
    """Classify a research expression without creating or authorizing an order.

    Priority is intentionally strict:
    qualified individual stock -> optional long-call overlay -> sector proxy ->
    no trade. A required-data failure always fails closed before any fallback.
    """

    active_policy = policy or ExpressionPolicy()

    if not inputs.required_data_ok:
        return ExpressionDecision(
            expression=Expression.NO_TRADE,
            reason="REQUIRED_DATA_ERROR",
        )

    if inputs.individual_r2_qualified:
        option_overlay_eligible = (
            inputs.option_quality_ok
            and inputs.option_dte is not None
            and active_policy.min_long_call_dte
            <= inputs.option_dte
            <= active_policy.max_long_call_dte
        )
        if option_overlay_eligible:
            return ExpressionDecision(
                expression=Expression.SHARES_PLUS_LONG_CALL,
                reason="R2_QUALIFIED_AND_LONG_CALL_QUALITY_OK",
                option_overlay_eligible=True,
            )
        return ExpressionDecision(
            expression=Expression.SHARES,
            reason="R2_QUALIFIED_SHARES_DEFAULT",
        )

    if not inputs.sector_breadth_ok:
        return ExpressionDecision(
            expression=Expression.NO_TRADE,
            reason="NO_INDIVIDUAL_SETUP_AND_SECTOR_BREADTH_NOT_CONFIRMED",
        )

    if inputs.sector_strength is SectorStrength.EXCEPTIONAL:
        if active_policy.allow_3x_sector_research:
            return ExpressionDecision(
                expression=Expression.SECTOR_3X,
                reason="EXCEPTIONAL_SECTOR_WITH_EXPLICIT_3X_RESEARCH_ENABLE",
            )
        return ExpressionDecision(
            expression=Expression.SECTOR_2X,
            reason="EXCEPTIONAL_SECTOR_DEFAULTS_TO_2X_WITHOUT_3X_ENABLE",
        )

    if inputs.sector_strength is SectorStrength.STRONG:
        return ExpressionDecision(
            expression=Expression.SECTOR_2X,
            reason="STRONG_SECTOR_PROXY_RESEARCH",
        )

    return ExpressionDecision(
        expression=Expression.NO_TRADE,
        reason="NO_QUALIFIED_ALPHA_EXPRESSION",
    )


def split_common_risk_budget(
    total_risk_budget: float,
    *,
    option_fraction: float,
) -> tuple[float, float]:
    """Split one common risk budget between shares and a long-call overlay.

    The function prevents a hybrid experiment from accidentally allocating a full
    stock risk budget plus a second full option risk budget.
    """

    if total_risk_budget < 0:
        raise ValueError("total_risk_budget must be non-negative")
    if not 0.0 <= option_fraction <= 1.0:
        raise ValueError("option_fraction must be between 0 and 1")

    option_risk = total_risk_budget * option_fraction
    share_risk = total_risk_budget - option_risk
    return share_risk, option_risk


def sgov_reserve_amount(
    account_cash: float,
    *,
    operational_cash_buffer: float,
    borrowed_cash: float = 0.0,
) -> float:
    """Return research-model cash eligible for the SGOV treasury reserve.

    Borrowed cash is excluded and the operational cash buffer is preserved. The
    result is a reserve target only; it does not create an order.
    """

    if account_cash < 0:
        raise ValueError("account_cash must be non-negative")
    if operational_cash_buffer < 0:
        raise ValueError("operational_cash_buffer must be non-negative")
    if borrowed_cash < 0:
        raise ValueError("borrowed_cash must be non-negative")

    unborrowed_cash = max(account_cash - borrowed_cash, 0.0)
    return max(unborrowed_cash - operational_cash_buffer, 0.0)
