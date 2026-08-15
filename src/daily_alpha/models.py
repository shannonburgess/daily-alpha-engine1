"""Domain models for reproducible instrument-selection decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class InstrumentSelected(StrEnum):
    OPTION = "OPTION"
    STOCK = "STOCK"
    NONE = "NONE"


class DecisionStatus(StrEnum):
    SELECTED = "SELECTED"
    NO_TRADE = "NO_TRADE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class OptionCandidate:
    symbol: str
    expiration: str
    strike: float
    option_type: str
    dte: int
    bid: float
    ask: float
    open_interest: int
    volume: int

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float:
        midpoint = self.midpoint
        return float("inf") if midpoint <= 0 else (self.ask - self.bid) / midpoint


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    price: float
    average_daily_dollar_volume: float
    eligible: bool = True


@dataclass(frozen=True)
class Decision:
    symbol: str
    status: DecisionStatus
    instrument_selected: InstrumentSelected
    fallback_reason: str
    selected_contract: OptionCandidate | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["instrument_selected"] = self.instrument_selected.value
        return payload

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        status: DecisionStatus,
        instrument_selected: InstrumentSelected,
        fallback_reason: str,
        selected_contract: OptionCandidate | None = None,
    ) -> "Decision":
        return cls(
            symbol=symbol,
            status=status,
            instrument_selected=instrument_selected,
            fallback_reason=fallback_reason,
            selected_contract=selected_contract,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
