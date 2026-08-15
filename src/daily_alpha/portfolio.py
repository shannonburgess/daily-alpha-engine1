"""Canonical, validated portfolio snapshots for risk and reporting."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class PortfolioDataStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class AssetType(StrEnum):
    STOCK = "STOCK"
    OPTION = "OPTION"


@dataclass(frozen=True)
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    def scaled(self, quantity: float, multiplier: int) -> Greeks:
        scale = quantity * multiplier
        return Greeks(
            delta=self.delta * scale,
            gamma=self.gamma * scale,
            theta=self.theta * scale,
            vega=self.vega * scale,
        )


@dataclass(frozen=True)
class Position:
    symbol: str
    asset_type: AssetType
    quantity: float
    mark: float
    cost_basis: float
    multiplier: int = 1
    sector: str = "UNKNOWN"
    expiration: str | None = None
    greeks: Greeks | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("position symbol is required")
        if self.mark < 0 or self.cost_basis < 0:
            raise ValueError("mark and cost_basis must be non-negative")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")
        if self.asset_type == AssetType.OPTION and self.greeks is None:
            raise ValueError("option positions require Greeks; do not estimate them")

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark * self.multiplier

    @property
    def gross_market_value(self) -> float:
        return abs(self.market_value)

    @property
    def position_greeks(self) -> Greeks | None:
        return None if self.greeks is None else self.greeks.scaled(self.quantity, self.multiplier)


@dataclass(frozen=True)
class PortfolioSnapshot:
    snapshot_id: str
    account_id: str
    source: str
    as_of: str
    ingested_at: str
    cash: float
    buying_power: float
    positions: tuple[Position, ...]
    data_status: PortfolioDataStatus
    reconciliation_errors: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        account_id: str,
        source: str,
        as_of: str,
        cash: float,
        buying_power: float,
        positions: Iterable[Position],
        data_status: PortfolioDataStatus = PortfolioDataStatus.AVAILABLE,
        reconciliation_errors: Iterable[str] = (),
    ) -> PortfolioSnapshot:
        if not snapshot_id or not account_id or not source:
            raise ValueError("snapshot_id, account_id, and source are required")
        datetime.fromisoformat(as_of)
        errors = tuple(reconciliation_errors)
        if errors and data_status == PortfolioDataStatus.AVAILABLE:
            data_status = PortfolioDataStatus.PARTIAL
        return cls(
            snapshot_id=snapshot_id,
            account_id=account_id,
            source=source,
            as_of=as_of,
            ingested_at=datetime.now(UTC).isoformat(),
            cash=cash,
            buying_power=buying_power,
            positions=tuple(positions),
            data_status=data_status,
            reconciliation_errors=errors,
        )

    @property
    def net_liquidating_value(self) -> float:
        return self.cash + sum(position.market_value for position in self.positions)

    @property
    def gross_exposure(self) -> float:
        return sum(position.gross_market_value for position in self.positions)

    @property
    def net_exposure(self) -> float:
        return sum(position.market_value for position in self.positions)

    @property
    def blocks_new_risk(self) -> bool:
        return self.data_status != PortfolioDataStatus.AVAILABLE or bool(
            self.reconciliation_errors
        )

    def aggregate_greeks(self) -> Greeks | None:
        option_positions = [p for p in self.positions if p.asset_type == AssetType.OPTION]
        if any(position.position_greeks is None for position in option_positions):
            return None
        totals = Greeks()
        for position in option_positions:
            greeks = position.position_greeks
            if greeks is not None:
                totals = Greeks(
                    delta=totals.delta + greeks.delta,
                    gamma=totals.gamma + greeks.gamma,
                    theta=totals.theta + greeks.theta,
                    vega=totals.vega + greeks.vega,
                )
        return totals

    def sector_exposure(self) -> dict[str, float]:
        exposure: dict[str, float] = {}
        for position in self.positions:
            exposure[position.sector] = exposure.get(position.sector, 0.0) + position.market_value
        return exposure

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_status"] = self.data_status.value
        for position in payload["positions"]:
            position["asset_type"] = position["asset_type"].value
        return payload
