"""Reconciled paper executor with normalized lifecycle execution receipts.

This composes zero-trade/state reconciliation with the exact paper receipt
contract so both ordinary realtime fills and durable ARMED replays emit the same
auditable execution evidence. It never enables live brokerage execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .execution_receipts import build_paper_execution_receipt
from .models import InstrumentSelected
from .pine_paper_orchestrator import _aware
from .pine_paper_reconciliation import ReconciledAwsPinePaperExecutor


class ReceiptReconciledAwsPinePaperExecutor(ReconciledAwsPinePaperExecutor):
    """Preserve reconciliation semantics and attach exact paper fill receipts."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._receipt_quote: Any | None = None

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        action = str(ingress.get("action", "")).upper()
        before_trade = self._before_trade(ingress)
        self._receipt_quote = None
        result = super().execute(ingress, now=timestamp)
        return self._attach_receipt(
            ingress=ingress,
            result=result,
            before_trade=before_trade,
            occurred_at=timestamp,
            replayed=False,
        )

    def replay_armed(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        before_trade = self._before_trade(ingress)
        self._receipt_quote = None
        result = super().replay_armed(ingress, now=timestamp)
        return self._attach_receipt(
            ingress=ingress,
            result=result,
            before_trade=before_trade,
            occurred_at=timestamp,
            replayed=True,
        )

    def _option_quote(self, trade, now):
        quote = super()._option_quote(trade, now)
        self._receipt_quote = quote
        return quote

    def _before_trade(self, ingress: Mapping[str, Any]) -> dict[str, Any] | None:
        action = str(ingress.get("action", "")).upper()
        symbol = str(ingress.get("symbol", "")).strip().upper()
        if action not in {"ADD", "PARTIAL", "EXIT"} or not symbol:
            return None
        open_trades = self.ledger.find_open(symbol)
        if len(open_trades) != 1:
            return None
        return open_trades[0].to_dict()

    def _attach_receipt(
        self,
        *,
        ingress: Mapping[str, Any],
        result: dict[str, Any],
        before_trade: dict[str, Any] | None,
        occurred_at: datetime,
        replayed: bool,
    ) -> dict[str, Any]:
        if result.get("disposition") != "EXECUTED_PAPER":
            return result

        action = str(ingress.get("action", "")).upper()
        paper = dict(result.get("paper") or {})
        paper["signal_id"] = _receipt_signal_id(
            ingress,
            occurred_at=occurred_at,
            replayed=replayed,
        )
        fill_price = self._fill_price(
            action=action,
            ingress=ingress,
            result=result,
            paper=paper,
            before_trade=before_trade,
        )
        receipt = build_paper_execution_receipt(
            action=action,
            paper=paper,
            fill_price=fill_price,
            before_trade=before_trade,
            account_id=getattr(self.ledger, "account_id", None),
            initial_risk_basis=_initial_risk_from_result(result),
            occurred_at=occurred_at,
        ).to_dict()
        paper["execution_receipt"] = receipt
        result["paper"] = paper
        result["execution_receipt"] = receipt
        return result

    def _fill_price(
        self,
        *,
        action: str,
        ingress: Mapping[str, Any],
        result: Mapping[str, Any],
        paper: dict[str, Any],
        before_trade: dict[str, Any] | None,
    ) -> float:
        if action == "ENTRY_LONG":
            trade = paper.get("trade")
            if not isinstance(trade, dict):
                raise ValueError("EXECUTION_RECEIPT_ENTRY_TRADE_MISSING")
            return float(trade["entry_price"])

        if before_trade is None:
            raise ValueError("EXECUTION_RECEIPT_PRIOR_TRADE_MISSING")
        instrument = str(before_trade.get("instrument", "")).upper()
        if instrument == InstrumentSelected.OPTION.value:
            if self._receipt_quote is None:
                raise ValueError("EXECUTION_RECEIPT_OPTION_QUOTE_MISSING")
            return float(
                self._receipt_quote.ask if action == "ADD" else self._receipt_quote.bid
            )
        if instrument == InstrumentSelected.STOCK.value:
            context = result.get("context")
            if isinstance(context, Mapping):
                replay_price = _positive_float_or_none(context.get("replay_market_price"))
                if replay_price is not None:
                    return replay_price
            return float(ingress["price"])
        raise ValueError("EXECUTION_RECEIPT_INSTRUMENT_INVALID")


def _receipt_signal_id(
    ingress: Mapping[str, Any],
    *,
    occurred_at: datetime,
    replayed: bool,
) -> str:
    signal_id = str(ingress.get("signal_id", "")).strip()
    if not replayed:
        return signal_id
    return f"{signal_id}-REPLAY-{occurred_at.strftime('%Y%m%dT%H%M%S')}"


def _initial_risk_from_result(result: Mapping[str, Any]) -> float | None:
    context = result.get("context")
    if not isinstance(context, Mapping):
        return None
    risk = context.get("risk")
    if not isinstance(risk, Mapping):
        return None
    snapshot = risk.get("risk_snapshot")
    if isinstance(snapshot, Mapping):
        proposed = snapshot.get("proposed")
        if isinstance(proposed, Mapping):
            value = _positive_float_or_none(proposed.get("planned_loss"))
            if value is not None:
                return value
    return _positive_float_or_none(risk.get("planned_loss"))


def _positive_float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
