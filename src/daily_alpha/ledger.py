"""Append-only, instrument-separated paper-trade ledgers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import InstrumentSelected


class TradeState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    signal_id: str
    symbol: str
    instrument: InstrumentSelected
    quantity: int
    entry_price: float
    entry_time: str
    state: TradeState = TradeState.OPEN
    exit_price: float | None = None
    exit_time: str | None = None
    realized_pnl: float | None = None
    fallback_reason: str = ""
    option_expiration: str | None = None
    option_strike: float | None = None
    option_type: str | None = None
    target_quantity: int | None = None
    runner_stage: str = "STARTER"
    add1_signal_id: str | None = None
    add2_signal_id: str | None = None
    harvest_signal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["instrument"] = self.instrument.value
        payload["state"] = self.state.value
        return payload


class PaperLedger:
    """Event ledger with distinct files for option and stock results."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def open_trade(
        self,
        *,
        signal_id: str,
        symbol: str,
        instrument: InstrumentSelected,
        quantity: int,
        entry_price: float,
        entry_time: datetime,
        fallback_reason: str,
        option_expiration: str | None = None,
        option_strike: float | None = None,
        option_type: str | None = None,
        target_quantity: int | None = None,
        runner_stage: str = "STARTER",
    ) -> PaperTrade:
        if instrument not in {InstrumentSelected.OPTION, InstrumentSelected.STOCK}:
            raise ValueError("Paper trade instrument must be OPTION or STOCK")
        if quantity <= 0 or entry_price <= 0:
            raise ValueError("Paper trade quantity and entry price must be positive")
        target = target_quantity or quantity
        if target < quantity:
            raise ValueError("Paper trade target quantity cannot be below current quantity")
        if self.find_open(symbol, instrument):
            raise ValueError(f"An open {instrument.value} paper trade already exists for {symbol}")

        trade = PaperTrade(
            trade_id=str(uuid4()),
            signal_id=signal_id,
            symbol=symbol.upper(),
            instrument=instrument,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=entry_time.isoformat(),
            fallback_reason=fallback_reason,
            option_expiration=option_expiration,
            option_strike=option_strike,
            option_type=option_type,
            target_quantity=target,
            runner_stage=runner_stage,
        )
        self._append(
            instrument,
            {"event": "OPEN", "signal_id": signal_id, "trade": trade.to_dict()},
        )
        return trade

    def add_trade(
        self,
        trade: PaperTrade,
        *,
        signal_id: str,
        quantity: int,
        fill_price: float,
        fill_time: datetime,
        runner_stage: str,
    ) -> PaperTrade:
        if trade.state != TradeState.OPEN:
            raise ValueError("Only an open paper trade can be increased")
        if signal_id in {trade.add1_signal_id, trade.add2_signal_id}:
            return trade
        if quantity <= 0 or fill_price <= 0:
            raise ValueError("ADD quantity and fill price must be positive")
        expected_prior = {
            "ADD_1_ATR": "STARTER",
            "ADD_2_ATR": "ADD_1_ATR",
        }.get(runner_stage)
        if expected_prior is None:
            raise ValueError("Unsupported runner ADD stage")
        if trade.runner_stage != expected_prior:
            raise ValueError(
                f"Runner stage {runner_stage} requires prior stage {expected_prior}"
            )
        target = trade.target_quantity or trade.quantity
        if trade.quantity + quantity > target:
            raise ValueError("Runner ADD would exceed target quantity")

        new_quantity = trade.quantity + quantity
        weighted_entry = (
            trade.entry_price * trade.quantity + fill_price * quantity
        ) / new_quantity
        updates: dict[str, Any] = {
            "quantity": new_quantity,
            "entry_price": round(weighted_entry, 8),
            "runner_stage": runner_stage,
        }
        if runner_stage == "ADD_1_ATR":
            updates["add1_signal_id"] = signal_id
        else:
            updates["add2_signal_id"] = signal_id
        updated = replace(trade, **updates)
        self._append(
            trade.instrument,
            {
                "event": "ADD",
                "signal_id": signal_id,
                "fill_price": fill_price,
                "fill_quantity": quantity,
                "fill_time": fill_time.isoformat(),
                "runner_stage": runner_stage,
                "trade": updated.to_dict(),
            },
        )
        return updated

    def partial_trade(
        self,
        trade: PaperTrade,
        *,
        signal_id: str,
        quantity: int,
        fill_price: float,
        fill_time: datetime,
        runner_stage: str,
    ) -> PaperTrade:
        if trade.state != TradeState.OPEN:
            raise ValueError("Only an open paper trade can be reduced")
        if signal_id == trade.harvest_signal_id:
            return trade
        if runner_stage != "HARVEST_3_ATR":
            raise ValueError("Unsupported runner PARTIAL stage")
        if trade.runner_stage != "ADD_2_ATR":
            raise ValueError("HARVEST_3_ATR requires a fully built runner")
        if quantity <= 0 or quantity >= trade.quantity or fill_price < 0:
            raise ValueError("PARTIAL quantity/price is invalid")

        multiplier = 100 if trade.instrument == InstrumentSelected.OPTION else 1
        realized = (fill_price - trade.entry_price) * quantity * multiplier
        cumulative = (trade.realized_pnl or 0.0) + realized
        updated = replace(
            trade,
            quantity=trade.quantity - quantity,
            runner_stage=runner_stage,
            harvest_signal_id=signal_id,
            realized_pnl=round(cumulative, 2),
        )
        self._append(
            trade.instrument,
            {
                "event": "PARTIAL",
                "signal_id": signal_id,
                "fill_price": fill_price,
                "fill_quantity": quantity,
                "fill_time": fill_time.isoformat(),
                "runner_stage": runner_stage,
                "trade": updated.to_dict(),
            },
        )
        return updated

    def close_trade(
        self,
        trade: PaperTrade,
        *,
        exit_price: float,
        exit_time: datetime,
        signal_id: str | None = None,
    ) -> PaperTrade:
        if trade.state != TradeState.OPEN:
            raise ValueError("Only an open paper trade can be closed")
        if exit_price < 0:
            raise ValueError("Exit price cannot be negative")

        multiplier = 100 if trade.instrument == InstrumentSelected.OPTION else 1
        final_leg = (exit_price - trade.entry_price) * trade.quantity * multiplier
        cumulative = (trade.realized_pnl or 0.0) + final_leg
        closed = replace(
            trade,
            state=TradeState.CLOSED,
            exit_price=exit_price,
            exit_time=exit_time.isoformat(),
            realized_pnl=round(cumulative, 2),
        )
        self._append(
            trade.instrument,
            {
                "event": "CLOSE",
                "signal_id": signal_id or trade.signal_id,
                "trade": closed.to_dict(),
            },
        )
        return closed

    def find_open(
        self,
        symbol: str,
        instrument: InstrumentSelected | None = None,
    ) -> list[PaperTrade]:
        instruments = (
            [instrument]
            if instrument
            else [InstrumentSelected.OPTION, InstrumentSelected.STOCK]
        )
        open_by_id: dict[str, PaperTrade] = {}
        for selected in instruments:
            for event in self._events(selected):
                trade = _trade_from_dict(event["trade"])
                if trade.symbol != symbol.upper():
                    continue
                if event["event"] in {"OPEN", "ADD", "PARTIAL"}:
                    open_by_id[trade.trade_id] = trade
                elif event["event"] == "CLOSE":
                    open_by_id.pop(trade.trade_id, None)
        return list(open_by_id.values())

    def _path(self, instrument: InstrumentSelected) -> Path:
        name = (
            "option_trades.jsonl"
            if instrument == InstrumentSelected.OPTION
            else "stock_trades.jsonl"
        )
        return self.root / name

    def _append(self, instrument: InstrumentSelected, event: dict[str, Any]) -> None:
        with self._path(instrument).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _events(self, instrument: InstrumentSelected) -> list[dict[str, Any]]:
        path = self._path(instrument)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


def _trade_from_dict(payload: dict[str, Any]) -> PaperTrade:
    values = dict(payload)
    values["instrument"] = InstrumentSelected(values["instrument"])
    values["state"] = TradeState(values["state"])
    return PaperTrade(**values)
