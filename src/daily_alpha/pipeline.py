"""Paper-trading orchestration for approved Pine entry and exit signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .ledger import PaperLedger, PaperTrade
from .models import Decision, DecisionStatus, InstrumentSelected
from .signals import PineSignal, SignalAction
from .sizing import PortfolioLimits, size_long_option, size_stock


@dataclass(frozen=True)
class EntryPricing:
    option_premium: float | None = None
    stock_price: float | None = None
    stock_stop_price: float | None = None


class PaperTradingPipeline:
    """Convert approved instrument decisions into auditable paper trades."""

    def __init__(self, ledger: PaperLedger, limits: PortfolioLimits) -> None:
        self.ledger = ledger
        self.limits = limits

    def process_entry(
        self,
        *,
        signal: PineSignal,
        decision: Decision,
        pricing: EntryPricing,
    ) -> PaperTrade:
        if signal.action != SignalAction.ENTRY_LONG:
            raise ValueError("process_entry requires an ENTRY_LONG signal")
        if decision.status != DecisionStatus.SELECTED:
            raise ValueError("A paper trade requires a SELECTED instrument decision")
        if signal.symbol != decision.symbol:
            raise ValueError("Signal and instrument decision symbols do not match")

        if decision.instrument_selected == InstrumentSelected.OPTION:
            if pricing.option_premium is None or decision.selected_contract is None:
                raise ValueError("Selected option requires contract and premium data")
            size = size_long_option(premium=pricing.option_premium, limits=self.limits)
            contract = decision.selected_contract
            return self.ledger.open_trade(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                instrument=InstrumentSelected.OPTION,
                quantity=size.quantity,
                entry_price=pricing.option_premium,
                entry_time=signal.received_at,
                fallback_reason=decision.fallback_reason,
                option_expiration=contract.expiration,
                option_strike=contract.strike,
                option_type=contract.option_type,
            )

        if decision.instrument_selected == InstrumentSelected.STOCK:
            if pricing.stock_price is None or pricing.stock_stop_price is None:
                raise ValueError("Selected stock requires entry and stop prices")
            size = size_stock(
                share_price=pricing.stock_price,
                stop_price=pricing.stock_stop_price,
                limits=self.limits,
            )
            return self.ledger.open_trade(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                instrument=InstrumentSelected.STOCK,
                quantity=size.quantity,
                entry_price=pricing.stock_price,
                entry_time=signal.received_at,
                fallback_reason=decision.fallback_reason,
            )

        raise ValueError("Unsupported instrument decision")

    def process_exit(
        self,
        *,
        signal: PineSignal,
        option_exit_price: float | None = None,
        stock_exit_price: float | None = None,
        exit_time: datetime | None = None,
    ) -> list[PaperTrade]:
        """Apply the same approved Pine/Turtle exit to the selected instrument."""
        if signal.action != SignalAction.EXIT:
            raise ValueError("process_exit requires an EXIT signal")

        closed: list[PaperTrade] = []
        timestamp = exit_time or signal.received_at
        for trade in self.ledger.find_open(signal.symbol):
            if trade.instrument == InstrumentSelected.OPTION:
                if option_exit_price is None:
                    raise ValueError("Option exit price is required for an open option")
                closed.append(
                    self.ledger.close_trade(
                        trade,
                        exit_price=option_exit_price,
                        exit_time=timestamp,
                    )
                )
            else:
                if stock_exit_price is None:
                    raise ValueError("Stock exit price is required for an open stock")
                closed.append(
                    self.ledger.close_trade(
                        trade,
                        exit_price=stock_exit_price,
                        exit_time=timestamp,
                    )
                )
        return closed
