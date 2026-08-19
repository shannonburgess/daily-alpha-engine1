"""Paper executor wrapper that attaches normalized execution receipts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .execution_receipts import build_paper_execution_receipt
from .models import InstrumentSelected
from .pine_paper_orchestrator import AwsPinePaperExecutor


class ReceiptAwsPinePaperExecutor(AwsPinePaperExecutor):
    """Preserve the base paper logic and add an auditable fill receipt."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._receipt_quote: Any | None = None

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        action = str(ingress.get("action", "")).upper()
        symbol = str(ingress.get("symbol", "")).strip().upper()
        before_trade = None
        if action in {"ADD", "PARTIAL", "EXIT"} and symbol:
            open_trades = self.ledger.find_open(symbol)
            if len(open_trades) == 1:
                before_trade = open_trades[0].to_dict()

        self._receipt_quote = None
        result = super().execute(ingress, now=now)
        if result.get("disposition") != "EXECUTED_PAPER":
            return result

        paper = dict(result.get("paper") or {})
        paper["signal_id"] = str(ingress.get("signal_id", ""))
        fill_price = self._fill_price(
            action=action,
            ingress=ingress,
            paper=paper,
            before_trade=before_trade,
        )
        initial_risk = _initial_risk_from_result(result)
        receipt = build_paper_execution_receipt(
            action=action,
            paper=paper,
            fill_price=fill_price,
            before_trade=before_trade,
            account_id=getattr(self.ledger, "account_id", None),
            initial_risk_basis=initial_risk,
            occurred_at=now,
        ).to_dict()
        paper["execution_receipt"] = receipt
        result["paper"] = paper
        result["execution_receipt"] = receipt
        return result

    def _option_quote(self, trade, now):
        quote = super()._option_quote(trade, now)
        self._receipt_quote = quote
        return quote

    def _fill_price(
        self,
        *,
        action: str,
        ingress: Mapping[str, Any],
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
            return float(ingress["price"])
        raise ValueError("EXECUTION_RECEIPT_INSTRUMENT_INVALID")


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
