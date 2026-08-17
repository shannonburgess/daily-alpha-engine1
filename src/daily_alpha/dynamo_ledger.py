"""Durable DynamoDB-backed paper-trade ledger for AWS staging.

The ledger keeps one conditional current-position record per instrument/symbol and
append-only OPEN/ADD/PARTIAL/CLOSE audit events per trade. Live brokerage
execution is not part of this module.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from .ledger import PaperTrade, TradeState
from .models import InstrumentSelected


class LedgerStorageError(RuntimeError):
    """Raised when durable paper-ledger storage cannot be used safely."""


class DynamoPaperLedger:
    """PaperLedger-compatible durable store using a single DynamoDB table."""

    DEFAULT_TABLE_NAME = "daily-alpha-paper-ledger-staging"
    DEFAULT_ACCOUNT_ID = "paper-staging"

    def __init__(
        self,
        *,
        table_name: str | None = None,
        account_id: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.table_name = (
            table_name
            or os.getenv("DAILY_ALPHA_PAPER_LEDGER_TABLE")
            or self.DEFAULT_TABLE_NAME
        ).strip()
        self.account_id = (
            account_id
            or os.getenv("DAILY_ALPHA_PAPER_ACCOUNT_ID")
            or self.DEFAULT_ACCOUNT_ID
        ).strip()
        if not self.table_name or not self.account_id:
            raise LedgerStorageError("PAPER_LEDGER_CONFIGURATION_INVALID")

        if client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - Lambda includes boto3
                raise LedgerStorageError("BOTO3_UNAVAILABLE") from exc
            client = boto3.client("dynamodb")
        self.client = client

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

        existing = self.find_open(symbol, instrument)
        if existing:
            if existing[0].signal_id == signal_id:
                return existing[0]
            raise ValueError(
                f"An open {instrument.value} paper trade already exists for {symbol.upper()}"
            )

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
        current = self._current_item(trade)
        audit = self._audit_item("OPEN", trade, entry_time, event_signal_id=signal_id)

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": current,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": audit,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except Exception as exc:
            if _aws_error_code(exc) in {
                "TransactionCanceledException",
                "ConditionalCheckFailedException",
            }:
                existing = self.find_open(symbol, instrument)
                if existing and existing[0].signal_id == signal_id:
                    return existing[0]
                if existing:
                    raise ValueError(
                        f"An open {instrument.value} paper trade already exists for "
                        f"{symbol.upper()}"
                    ) from exc
            raise _storage_error(exc) from exc
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
        return self._replace_current_with_audit(
            trade,
            updated,
            event="ADD",
            event_signal_id=signal_id,
            occurred_at=fill_time,
        )

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
        return self._replace_current_with_audit(
            trade,
            updated,
            event="PARTIAL",
            event_signal_id=signal_id,
            occurred_at=fill_time,
        )

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
        key = self._current_key(trade.instrument, trade.symbol)
        event_signal_id = signal_id or trade.signal_id
        audit = self._audit_item(
            "CLOSE",
            closed,
            exit_time,
            event_signal_id=event_signal_id,
        )

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Delete": {
                            "TableName": self.table_name,
                            "Key": key,
                            "ConditionExpression": "trade_id = :trade_id",
                            "ExpressionAttributeValues": {
                                ":trade_id": {"S": trade.trade_id}
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": audit,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except Exception as exc:
            if _aws_error_code(exc) in {
                "TransactionCanceledException",
                "ConditionalCheckFailedException",
            }:
                raise ValueError("Paper trade is no longer open") from exc
            raise _storage_error(exc) from exc
        return closed

    def find_open(
        self,
        symbol: str,
        instrument: InstrumentSelected | None = None,
    ) -> list[PaperTrade]:
        instruments = (
            (instrument,)
            if instrument is not None
            else (InstrumentSelected.OPTION, InstrumentSelected.STOCK)
        )
        results: list[PaperTrade] = []
        for selected in instruments:
            try:
                response = self.client.get_item(
                    TableName=self.table_name,
                    Key=self._current_key(selected, symbol),
                    ConsistentRead=True,
                )
            except Exception as exc:
                raise _storage_error(exc) from exc
            item = response.get("Item") if isinstance(response, dict) else None
            if item and "trade_json" in item:
                results.append(_trade_from_json(item["trade_json"]["S"]))
        return results

    def _replace_current_with_audit(
        self,
        prior: PaperTrade,
        updated: PaperTrade,
        *,
        event: str,
        event_signal_id: str,
        occurred_at: datetime,
    ) -> PaperTrade:
        current = self._current_item(updated)
        audit = self._audit_item(
            event,
            updated,
            occurred_at,
            event_signal_id=event_signal_id,
        )
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": current,
                            "ConditionExpression": "trade_id = :trade_id",
                            "ExpressionAttributeValues": {
                                ":trade_id": {"S": prior.trade_id}
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": audit,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except Exception as exc:
            if _aws_error_code(exc) in {
                "TransactionCanceledException",
                "ConditionalCheckFailedException",
            }:
                current_trades = self.find_open(prior.symbol, prior.instrument)
                if current_trades and _signal_was_applied(
                    current_trades[0], event_signal_id
                ):
                    return current_trades[0]
                raise ValueError("Paper runner update is no longer valid") from exc
            raise _storage_error(exc) from exc
        return updated

    def _current_key(
        self, instrument: InstrumentSelected, symbol: str
    ) -> dict[str, dict[str, str]]:
        return {
            "pk": {
                "S": (
                    f"ACCOUNT#{self.account_id}#POSITION#"
                    f"{instrument.value}#{symbol.upper()}"
                )
            },
            "sk": {"S": "OPEN"},
        }

    def _current_item(self, trade: PaperTrade) -> dict[str, dict[str, str]]:
        return {
            **self._current_key(trade.instrument, trade.symbol),
            "trade_id": {"S": trade.trade_id},
            "signal_id": {"S": trade.signal_id},
            "symbol": {"S": trade.symbol},
            "instrument": {"S": trade.instrument.value},
            "state": {"S": trade.state.value},
            "runner_stage": {"S": trade.runner_stage},
            "trade_json": {"S": json.dumps(trade.to_dict(), sort_keys=True)},
        }

    def _audit_item(
        self,
        event: str,
        trade: PaperTrade,
        occurred_at: datetime,
        *,
        event_signal_id: str,
    ) -> dict[str, dict[str, str]]:
        return {
            "pk": {"S": f"ACCOUNT#{self.account_id}#TRADE#{trade.trade_id}"},
            "sk": {
                "S": (
                    f"EVENT#{occurred_at.isoformat()}#{event}#"
                    f"{event_signal_id}"
                )
            },
            "event": {"S": event},
            "trade_id": {"S": trade.trade_id},
            "signal_id": {"S": event_signal_id},
            "symbol": {"S": trade.symbol},
            "instrument": {"S": trade.instrument.value},
            "state": {"S": trade.state.value},
            "runner_stage": {"S": trade.runner_stage},
            "trade_json": {"S": json.dumps(trade.to_dict(), sort_keys=True)},
        }


def _signal_was_applied(trade: PaperTrade, signal_id: str) -> bool:
    return signal_id in {
        trade.signal_id,
        trade.add1_signal_id,
        trade.add2_signal_id,
        trade.harvest_signal_id,
    }


def _trade_from_json(value: str) -> PaperTrade:
    payload = json.loads(value)
    payload["instrument"] = InstrumentSelected(payload["instrument"])
    payload["state"] = TradeState(payload["state"])
    return PaperTrade(**payload)


def _aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""


def _storage_error(exc: Exception) -> LedgerStorageError:
    code = _aws_error_code(exc)
    suffix = code.upper() if code else "REQUEST_FAILED"
    return LedgerStorageError(f"DYNAMODB_{suffix}")
