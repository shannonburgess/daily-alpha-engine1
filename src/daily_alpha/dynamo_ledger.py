"""Durable DynamoDB-backed paper-trade ledger for AWS staging.

The ledger keeps one conditional current-position record per instrument/symbol and
append-only OPEN/CLOSE audit events per trade.  Live brokerage execution is not
part of this module.
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
    """PaperLedger-compatible durable store using a single DynamoDB table.

    Table schema:
      partition key: ``pk`` (String)
      sort key:      ``sk`` (String)

    Current open positions use one conditional item at an account/instrument/
    symbol key.  Audit events use a separate trade partition so OPEN and CLOSE
    records remain immutable and reproducible.
    """

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
    ) -> PaperTrade:
        if instrument not in {InstrumentSelected.OPTION, InstrumentSelected.STOCK}:
            raise ValueError("Paper trade instrument must be OPTION or STOCK")
        if quantity <= 0 or entry_price <= 0:
            raise ValueError("Paper trade quantity and entry price must be positive")

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
        )
        current = self._current_item(trade)
        audit = self._audit_item("OPEN", trade, entry_time)

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

    def close_trade(
        self,
        trade: PaperTrade,
        *,
        exit_price: float,
        exit_time: datetime,
    ) -> PaperTrade:
        if trade.state != TradeState.OPEN:
            raise ValueError("Only an open paper trade can be closed")
        if exit_price < 0:
            raise ValueError("Exit price cannot be negative")

        multiplier = 100 if trade.instrument == InstrumentSelected.OPTION else 1
        pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier
        closed = replace(
            trade,
            state=TradeState.CLOSED,
            exit_price=exit_price,
            exit_time=exit_time.isoformat(),
            realized_pnl=round(pnl, 2),
        )
        key = self._current_key(trade.instrument, trade.symbol)
        audit = self._audit_item("CLOSE", closed, exit_time)

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
            "trade_json": {"S": json.dumps(trade.to_dict(), sort_keys=True)},
        }

    def _audit_item(
        self, event: str, trade: PaperTrade, occurred_at: datetime
    ) -> dict[str, dict[str, str]]:
        return {
            "pk": {"S": f"ACCOUNT#{self.account_id}#TRADE#{trade.trade_id}"},
            "sk": {"S": f"EVENT#{occurred_at.isoformat()}#{event}"},
            "event": {"S": event},
            "trade_id": {"S": trade.trade_id},
            "signal_id": {"S": trade.signal_id},
            "symbol": {"S": trade.symbol},
            "instrument": {"S": trade.instrument.value},
            "state": {"S": trade.state.value},
            "trade_json": {"S": json.dumps(trade.to_dict(), sort_keys=True)},
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
