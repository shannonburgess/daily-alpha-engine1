"""Risk-based paper position sizing for options and stocks."""

from __future__ import annotations

from dataclasses import dataclass

from .models import InstrumentSelected


class SizingError(ValueError):
    """Raised when a position cannot be sized safely."""


@dataclass(frozen=True)
class PortfolioLimits:
    nav: float
    risk_per_trade_pct: float = 0.005
    max_capital_per_trade_pct: float = 0.02

    def __post_init__(self) -> None:
        if self.nav <= 0:
            raise SizingError("NAV must be positive")
        if not 0 < self.risk_per_trade_pct <= 0.05:
            raise SizingError("risk_per_trade_pct must be between 0 and 5%")
        if not 0 < self.max_capital_per_trade_pct <= 0.20:
            raise SizingError("max_capital_per_trade_pct must be between 0 and 20%")


@dataclass(frozen=True)
class SizingResult:
    instrument: InstrumentSelected
    quantity: int
    unit_entry_price: float
    capital_required: float
    risk_budget: float
    estimated_max_loss: float
    sizing_reason: str


def size_long_option(
    *,
    premium: float,
    limits: PortfolioLimits,
    contract_multiplier: int = 100,
) -> SizingResult:
    """Size a long option using premium paid as the maximum-loss estimate."""
    if premium <= 0 or contract_multiplier <= 0:
        raise SizingError("Option premium and multiplier must be positive")

    unit_cost = premium * contract_multiplier
    risk_budget = limits.nav * limits.risk_per_trade_pct
    capital_limit = limits.nav * limits.max_capital_per_trade_pct
    quantity = int(min(risk_budget, capital_limit) // unit_cost)
    if quantity < 1:
        raise SizingError("Risk budget is too small for one option contract")

    capital = quantity * unit_cost
    return SizingResult(
        instrument=InstrumentSelected.OPTION,
        quantity=quantity,
        unit_entry_price=premium,
        capital_required=capital,
        risk_budget=risk_budget,
        estimated_max_loss=capital,
        sizing_reason="LONG_OPTION_PREMIUM_AT_RISK",
    )


def size_stock(
    *,
    share_price: float,
    stop_price: float,
    limits: PortfolioLimits,
) -> SizingResult:
    """Size shares by stop distance while respecting the capital cap."""
    if share_price <= 0 or stop_price <= 0 or stop_price >= share_price:
        raise SizingError("Stock stop must be positive and below the entry price")

    per_share_risk = share_price - stop_price
    risk_budget = limits.nav * limits.risk_per_trade_pct
    capital_limit = limits.nav * limits.max_capital_per_trade_pct
    by_risk = int(risk_budget // per_share_risk)
    by_capital = int(capital_limit // share_price)
    quantity = min(by_risk, by_capital)
    if quantity < 1:
        raise SizingError("Risk or capital budget is too small for one share")

    return SizingResult(
        instrument=InstrumentSelected.STOCK,
        quantity=quantity,
        unit_entry_price=share_price,
        capital_required=quantity * share_price,
        risk_budget=risk_budget,
        estimated_max_loss=quantity * per_share_risk,
        sizing_reason="STOCK_STOP_DISTANCE_AND_CAPITAL_CAP",
    )
