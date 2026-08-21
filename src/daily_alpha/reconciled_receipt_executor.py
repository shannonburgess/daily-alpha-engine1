"""Reconciled stock-primary PAPER executor with exact lifecycle receipts.

New and managed automated PAPER positions are STOCK only. Confirmed Pine/scanner
signal prices are model-validation fills under the frozen strategy semantics.
Options are user-directed and broker-chain sourced; this module never quotes,
opens, adds to, partially closes, or exits an option position autonomously.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .execution_receipts import build_paper_execution_receipt
from .models import InstrumentSelected
from .pine_paper_orchestrator import (
    STOCK_PRIMARY_POLICY,
    AwsPinePaperExecutor,
    PinePaperExecutionError,
    _aware,
    _execution_result,
    _required_text,
)
from .pine_paper_reconciliation import (
    ReconciledAwsPinePaperExecutor,
    _result,
    prepare_armed_replay,
)

MIN_STOCK_PRICE = 10.0


class ReceiptReconciledAwsPinePaperExecutor(ReconciledAwsPinePaperExecutor):
    """Canonical STOCK-only PAPER executor with exact audit receipts."""

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        before_trade = self._before_trade(ingress)
        result = self._execute_stock_primary(ingress, now=timestamp)
        result["evaluated_at"] = timestamp.isoformat()
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
        result = self._replay_stock_primary(ingress, now=timestamp)
        result["evaluated_at"] = timestamp.isoformat()
        return self._attach_receipt(
            ingress=ingress,
            result=result,
            before_trade=before_trade,
            occurred_at=timestamp,
            replayed=True,
        )

    def _execute_stock_primary(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        action = str(ingress.get("action", "")).upper()
        if action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
            raise PinePaperExecutionError("PINE_ACTION_UNSUPPORTED")
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()

        if action == "ENTRY_LONG":
            # Model validation uses the confirmed signal price and therefore does
            # not require a separate market-hours quote lookup for the entry fill.
            result = AwsPinePaperExecutor._entry(self, ingress, now)
            context = dict(result.get("context") or {})
            context.update(_policy_context())
            result["context"] = context
            return result

        open_trades = self.ledger.find_open(symbol)
        if not open_trades:
            return _result(
                disposition="STATE_MISMATCH",
                reason="TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER",
                action=action,
                symbol=symbol,
                context={
                    **_policy_context(),
                    "state_mismatch": True,
                    "orphan_action": action,
                    "signal_id": str(ingress.get("signal_id", "")),
                    "runner_stage": ingress.get("runner_stage"),
                    "replay_allowed": False,
                },
            )
        if len(open_trades) != 1:
            raise PinePaperExecutionError("MULTIPLE_OPEN_INSTRUMENTS_FOR_SYMBOL")
        if open_trades[0].instrument != InstrumentSelected.STOCK:
            return _execution_result(
                disposition="NO_TRADE",
                reason="USER_DIRECTED_OPTION_MANAGEMENT_REQUIRED",
                action=action,
                symbol=symbol,
                context={
                    **_policy_context(),
                    "automated_option_management": False,
                },
            )

        result = AwsPinePaperExecutor._runner(self, ingress, now)
        context = dict(result.get("context") or {})
        context.update(_policy_context())
        result["context"] = context
        return result

    def _replay_stock_primary(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        action = str(ingress.get("action", "")).upper()
        if action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
            raise PinePaperExecutionError("PINE_ACTION_UNSUPPORTED")
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()

        open_trades = self.ledger.find_open(symbol)
        if action in {"ADD", "PARTIAL", "EXIT"} and not open_trades:
            return _result(
                disposition="STATE_MISMATCH",
                reason="TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER",
                action=action,
                symbol=symbol,
                context={
                    **_policy_context(),
                    "state_mismatch": True,
                    "orphan_action": action,
                    "signal_id": str(ingress.get("signal_id", "")),
                    "replay_allowed": False,
                },
            )
        if len(open_trades) > 1:
            raise PinePaperExecutionError("MULTIPLE_OPEN_INSTRUMENTS_FOR_SYMBOL")
        if open_trades and open_trades[0].instrument != InstrumentSelected.STOCK:
            return _result(
                disposition="NO_TRADE",
                reason="USER_DIRECTED_OPTION_MANAGEMENT_REQUIRED",
                action=action,
                symbol=symbol,
                context={**_policy_context(), "automated_option_management": False},
            )

        try:
            signal_price = float(ingress["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PinePaperExecutionError("REPLAY_SIGNAL_PRICE_INVALID") from exc
        if signal_price <= 0:
            raise PinePaperExecutionError("REPLAY_SIGNAL_PRICE_INVALID")

        replay = prepare_armed_replay(
            ingress,
            market_price=signal_price,
            now=now,
        )
        if not replay.should_execute:
            disposition = (
                "ARMED_FOR_NEXT_TRADABLE_WINDOW"
                if replay.status == "WAIT_REVALIDATION"
                else replay.status
            )
            return _result(
                disposition=disposition,
                reason=replay.reason,
                action=action,
                symbol=symbol,
                context={
                    **_policy_context(),
                    "replay_attempted": True,
                    "decision": replay.to_dict(),
                },
            )

        assert replay.ingress is not None
        result = self._execute_stock_primary(replay.ingress, now=now)
        context = dict(result.get("context") or {})
        context.update(
            {
                **_policy_context(),
                "replayed_from_armed_signal": True,
                "origin_signal_id": str(ingress.get("signal_id", "")),
                "origin_signal_price": signal_price,
                "model_validation_fill_price": signal_price,
            }
        )
        result["context"] = context
        return result

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
            initial_risk_basis=_persisted_initial_risk(paper, before_trade)
            or _initial_risk_from_result(result),
            occurred_at=occurred_at,
        ).to_dict()
        paper["execution_receipt"] = receipt
        result["paper"] = paper
        result["execution_receipt"] = receipt
        return result

    @staticmethod
    def _fill_price(
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
            if str(trade.get("instrument", "")).upper() != InstrumentSelected.STOCK.value:
                raise ValueError("EXECUTION_RECEIPT_AUTOMATED_OPTION_FORBIDDEN")
            return float(trade["entry_price"])

        if before_trade is None:
            raise ValueError("EXECUTION_RECEIPT_PRIOR_TRADE_MISSING")
        if str(before_trade.get("instrument", "")).upper() != InstrumentSelected.STOCK.value:
            raise ValueError("EXECUTION_RECEIPT_AUTOMATED_OPTION_FORBIDDEN")
        context = result.get("context")
        if isinstance(context, Mapping):
            replay_price = _positive_float_or_none(
                context.get("model_validation_fill_price")
                or context.get("replay_market_price")
            )
            if replay_price is not None:
                return replay_price
        return float(ingress["price"])


def _policy_context() -> dict[str, Any]:
    return {
        "execution_policy": STOCK_PRIMARY_POLICY,
        "new_entry_instrument": InstrumentSelected.STOCK.value,
        "automated_options_execution": False,
        "automated_option_management": False,
        "options_mode": "USER_DIRECTED_BROKER_CHAIN",
        "fill_model": "CONFIRMED_SIGNAL_PRICE_PROCESS_ORDERS_ON_CLOSE",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


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


def _persisted_initial_risk(
    paper: Mapping[str, Any], before_trade: Mapping[str, Any] | None
) -> float | None:
    if before_trade is not None:
        value = _positive_float_or_none(before_trade.get("initial_risk_basis"))
        if value is not None:
            return value
    trade = paper.get("trade")
    if isinstance(trade, Mapping):
        value = _positive_float_or_none(trade.get("initial_risk_basis"))
        if value is not None:
            return value
    values = paper.get("updated_trades") or paper.get("closed_trades")
    if isinstance(values, list) and len(values) == 1 and isinstance(values[0], Mapping):
        return _positive_float_or_none(values[0].get("initial_risk_basis"))
    return None


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
