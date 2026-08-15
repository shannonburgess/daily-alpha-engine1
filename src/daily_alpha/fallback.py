"""OPTION -> STOCK instrument fallback engine."""

from __future__ import annotations

from collections.abc import Iterable

from .config import OptionQualityRules, StockFallbackRules
from .models import (
    Decision,
    DecisionStatus,
    InstrumentSelected,
    OptionCandidate,
    StockCandidate,
)


class InstrumentFallbackEngine:
    """Select an instrument without masking option-data failures.

    Hierarchy:
      qualified option -> eligible liquid stock -> no trade

    A stale or failed ORATS/API response is always DATA_ERROR. It never
    authorizes a stock substitution.
    """

    def __init__(
        self,
        option_rules: OptionQualityRules | None = None,
        stock_rules: StockFallbackRules | None = None,
    ) -> None:
        self.option_rules = option_rules or OptionQualityRules()
        self.stock_rules = stock_rules or StockFallbackRules()

    def select(
        self,
        *,
        symbol: str,
        signal_active: bool,
        risk_gate_passed: bool,
        option_data_fresh: bool,
        option_data_available: bool,
        options: Iterable[OptionCandidate],
        stock: StockCandidate | None,
    ) -> Decision:
        if not signal_active:
            return self._none(symbol, "NO_ACTIVE_PINE_SIGNAL")

        if not risk_gate_passed:
            return self._none(symbol, "PORTFOLIO_RISK_GATE_FAILED")

        if not option_data_available or not option_data_fresh:
            return Decision.create(
                symbol=symbol,
                status=DecisionStatus.DATA_ERROR,
                instrument_selected=InstrumentSelected.NONE,
                fallback_reason="ORATS_DATA_UNAVAILABLE_OR_STALE",
            )

        qualified = [candidate for candidate in options if self._option_passes(candidate)]
        if qualified:
            selected = min(
                qualified,
                key=lambda candidate: (
                    candidate.spread_pct,
                    -candidate.open_interest,
                    -candidate.volume,
                ),
            )
            return Decision.create(
                symbol=symbol,
                status=DecisionStatus.SELECTED,
                instrument_selected=InstrumentSelected.OPTION,
                fallback_reason="QUALIFIED_OPTION_SELECTED",
                selected_contract=selected,
            )

        if stock is not None and self._stock_passes(stock):
            return Decision.create(
                symbol=symbol,
                status=DecisionStatus.SELECTED,
                instrument_selected=InstrumentSelected.STOCK,
                fallback_reason="NO_OPTION_PASSED_QUALITY_FILTERS_STOCK_ELIGIBLE",
            )

        return self._none(symbol, "NO_QUALIFIED_OPTION_AND_STOCK_INELIGIBLE")

    def _option_passes(self, option: OptionCandidate) -> bool:
        rules = self.option_rules
        return (
            rules.min_dte <= option.dte <= rules.max_dte
            and option.bid >= rules.min_bid
            and option.ask >= option.bid
            and option.spread_pct <= rules.max_spread_pct
            and option.open_interest >= rules.min_open_interest
            and option.volume >= rules.min_volume
            and (
                option.delta is None
                or rules.min_abs_delta <= abs(option.delta) <= rules.max_abs_delta
            )
        )

    def _stock_passes(self, stock: StockCandidate) -> bool:
        rules = self.stock_rules
        return (
            stock.eligible
            and stock.price >= rules.min_price
            and stock.average_daily_dollar_volume
            >= rules.min_average_daily_dollar_volume
        )

    @staticmethod
    def _none(symbol: str, reason: str) -> Decision:
        return Decision.create(
            symbol=symbol,
            status=DecisionStatus.NO_TRADE,
            instrument_selected=InstrumentSelected.NONE,
            fallback_reason=reason,
        )
