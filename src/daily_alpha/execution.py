"""Realistic paper-execution records and cost metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .models import InstrumentSelected


class FillStatus(StrEnum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    MISSED = "MISSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ExecutionIntent:
    execution_id: str
    trade_id: str
    symbol: str
    instrument: InstrumentSelected
    requested_quantity: int
    signal_price: float
    bid: float
    ask: float
    intended_limit: float
    signal_time: str

    def __post_init__(self) -> None:
        if not self.execution_id or not self.trade_id or not self.symbol:
            raise ValueError("execution_id, trade_id, and symbol are required")
        if self.instrument == InstrumentSelected.NONE:
            raise ValueError("execution instrument must be OPTION or STOCK")
        if self.requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if min(self.signal_price, self.bid, self.ask, self.intended_limit) < 0:
            raise ValueError("execution prices cannot be negative")
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        _timestamp(self.signal_time)

    @property
    def multiplier(self) -> int:
        return 100 if self.instrument == InstrumentSelected.OPTION else 1

    @property
    def quoted_spread(self) -> float:
        return self.ask - self.bid

    @property
    def quoted_spread_pct(self) -> float:
        midpoint = (self.bid + self.ask) / 2
        return float("inf") if midpoint <= 0 else self.quoted_spread / midpoint


@dataclass(frozen=True)
class ExecutionResult:
    intent: ExecutionIntent
    status: FillStatus
    filled_quantity: int
    average_fill_price: float | None
    commission: float
    fill_time: str | None
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        if self.filled_quantity < 0 or self.filled_quantity > self.intent.requested_quantity:
            raise ValueError("filled_quantity is outside requested quantity")
        if self.commission < 0:
            raise ValueError("commission cannot be negative")
        if self.status in {FillStatus.FILLED, FillStatus.PARTIAL}:
            if self.average_fill_price is None or self.average_fill_price < 0 or not self.fill_time:
                raise ValueError("filled executions require a non-negative price and fill_time")
            _timestamp(self.fill_time)
        elif self.filled_quantity != 0 or self.average_fill_price is not None:
            raise ValueError("missed/rejected executions cannot contain fills")
        if self.status == FillStatus.FILLED and self.filled_quantity != self.intent.requested_quantity:
            raise ValueError("FILLED requires the complete requested quantity")
        if self.status == FillStatus.PARTIAL and not (
            0 < self.filled_quantity < self.intent.requested_quantity
        ):
            raise ValueError("PARTIAL requires an incomplete positive fill")

    @property
    def fill_rate(self) -> float:
        return self.filled_quantity / self.intent.requested_quantity

    @property
    def slippage_per_unit(self) -> float | None:
        if self.average_fill_price is None:
            return None
        return self.average_fill_price - self.intent.intended_limit

    @property
    def signal_slippage_per_unit(self) -> float | None:
        if self.average_fill_price is None:
            return None
        return self.average_fill_price - self.intent.signal_price

    @property
    def slippage_cost(self) -> float:
        slippage = self.slippage_per_unit
        if slippage is None:
            return 0.0
        return slippage * self.filled_quantity * self.intent.multiplier

    @property
    def latency_seconds(self) -> float | None:
        if not self.fill_time:
            return None
        return (_timestamp(self.fill_time) - _timestamp(self.intent.signal_time)).total_seconds()

    def net_pnl(self, *, exit_price: float, exit_commission: float = 0.0) -> float | None:
        if self.average_fill_price is None:
            return None
        if exit_price < 0 or exit_commission < 0:
            raise ValueError("exit price and commission cannot be negative")
        gross = (
            (exit_price - self.average_fill_price)
            * self.filled_quantity
            * self.intent.multiplier
        )
        return gross - self.commission - exit_commission

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["intent"]["instrument"] = self.intent.instrument.value
        payload["status"] = self.status.value
        payload["metrics"] = {
            "fill_rate": self.fill_rate,
            "quoted_spread": self.intent.quoted_spread,
            "quoted_spread_pct": self.intent.quoted_spread_pct,
            "slippage_per_unit": self.slippage_per_unit,
            "signal_slippage_per_unit": self.signal_slippage_per_unit,
            "slippage_cost": self.slippage_cost,
            "latency_seconds": self.latency_seconds,
        }
        return payload


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("execution timestamps must be timezone-aware")
    return parsed
