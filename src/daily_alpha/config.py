"""Typed configuration for option quality and stock fallback rules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionQualityRules:
    min_dte: int = 45
    max_dte: int = 75
    max_spread_pct: float = 0.15
    min_open_interest: int = 100
    min_volume: int = 10
    min_bid: float = 0.05
    min_abs_delta: float = 0.35
    max_abs_delta: float = 0.70


@dataclass(frozen=True)
class StockFallbackRules:
    # Daily Alpha's broader actionable universe uses a $10 underlying floor.
    # The SH24/SH25 TradingView control/challenger remain frozen at their audited
    # $25 Pine floor so the prospective shadow comparison is not contaminated.
    min_price: float = 10.0
    min_average_daily_dollar_volume: float = 50_000_000.0
