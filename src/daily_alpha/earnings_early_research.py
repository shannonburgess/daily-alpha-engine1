"""Research-only scenario model for 60%-70% earnings Gap & Go EARLY events.

This module intentionally does not connect to the paper or live execution path. It
compares alternative research treatments for an already-classified
EARNINGS_GAP_GO_EARLY event so Daily Alpha can test whether an early starter adds
value before any rule is promoted into paper trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EarlyConfirmationRule(StrEnum):
    CLOSE_ABOVE_EVENT_HIGH = "CLOSE_ABOVE_EVENT_HIGH"
    CLOSE_ABOVE_EVENT_CLOSE = "CLOSE_ABOVE_EVENT_CLOSE"


@dataclass(frozen=True)
class EarlyEventPath:
    event_close: float
    event_high: float
    forward_closes: tuple[float, ...]
    exit_price: float


@dataclass(frozen=True)
class EarlyScenarioResult:
    scenario: str
    starter_fraction: float
    final_fraction: float
    confirmation_day: int | None
    confirmation_price: float | None
    normalized_return_pct: float


def first_confirmation(
    path: EarlyEventPath,
    *,
    rule: EarlyConfirmationRule = EarlyConfirmationRule.CLOSE_ABOVE_EVENT_HIGH,
    max_days: int = 2,
) -> tuple[int, float] | None:
    """Return the first T+N close that confirms the EARLY event.

    Day numbers are one-based: the first forward close is T+1. A confirmation
    after ``max_days`` is ignored so tests can compare T+1 and T+2 policies.
    """
    _validate_path(path)
    if max_days < 1:
        raise ValueError("max_days must be at least 1")

    threshold = (
        path.event_high
        if rule == EarlyConfirmationRule.CLOSE_ABOVE_EVENT_HIGH
        else path.event_close
    )
    for day, close in enumerate(path.forward_closes[:max_days], start=1):
        if close > threshold:
            return day, close
    return None


def compare_early_entry_paths(
    path: EarlyEventPath,
    *,
    starter_fraction: float = 0.25,
    full_fraction: float = 0.50,
    confirmation_rule: EarlyConfirmationRule = EarlyConfirmationRule.CLOSE_ABOVE_EVENT_HIGH,
    max_confirmation_days: int = 2,
) -> tuple[EarlyScenarioResult, ...]:
    """Compare no-entry, starter-only, and starter-then-scale research paths.

    Returns are normalized to the strategy's full target exposure. For example,
    a 25% starter that gains 20% contributes +5 percentage points of normalized
    target return. These are research comparison metrics, not portfolio CAGR.
    """
    _validate_path(path)
    if not 0.0 < starter_fraction <= full_fraction <= 1.0:
        raise ValueError("fractions must satisfy 0 < starter <= full <= 1")

    starter_leg = starter_fraction * (path.exit_price / path.event_close - 1.0)
    confirmation = first_confirmation(
        path,
        rule=confirmation_rule,
        max_days=max_confirmation_days,
    )

    results = [
        EarlyScenarioResult(
            scenario="NO_ENTRY",
            starter_fraction=0.0,
            final_fraction=0.0,
            confirmation_day=None,
            confirmation_price=None,
            normalized_return_pct=0.0,
        ),
        EarlyScenarioResult(
            scenario="STARTER_ONLY",
            starter_fraction=starter_fraction,
            final_fraction=starter_fraction,
            confirmation_day=None,
            confirmation_price=None,
            normalized_return_pct=round(starter_leg * 100.0, 4),
        ),
    ]

    if confirmation is None:
        scale_return = starter_leg
        confirmation_day = None
        confirmation_price = None
        final_fraction = starter_fraction
    else:
        confirmation_day, confirmation_price = confirmation
        added_fraction = full_fraction - starter_fraction
        added_leg = added_fraction * (path.exit_price / confirmation_price - 1.0)
        scale_return = starter_leg + added_leg
        final_fraction = full_fraction

    results.append(
        EarlyScenarioResult(
            scenario="STARTER_THEN_CONFIRM",
            starter_fraction=starter_fraction,
            final_fraction=final_fraction,
            confirmation_day=confirmation_day,
            confirmation_price=confirmation_price,
            normalized_return_pct=round(scale_return * 100.0, 4),
        )
    )
    return tuple(results)


def _validate_path(path: EarlyEventPath) -> None:
    prices = (path.event_close, path.event_high, path.exit_price, *path.forward_closes)
    if any(price <= 0 for price in prices):
        raise ValueError("all prices must be positive")
    if path.event_high < path.event_close:
        raise ValueError("event_high must be greater than or equal to event_close")
