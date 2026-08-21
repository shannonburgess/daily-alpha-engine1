"""Stock-primary PAPER execution for Daily Alpha model validation.

The objective of this policy is to isolate signal/model quality from option-chain
selection. New PAPER entries are shares only and use the confirmed Pine/scanner
signal price as the model-validation fill, matching the frozen v2.4 Pine strategy's
``process_orders_on_close=true`` semantics. ORATS is not consulted for a new stock
entry or for management of a stock PAPER position.

Legacy OPTION paper positions remain readable/manageable through the existing
reconciled executor so a strategy cutover never strands an old position. This
module never enables live brokerage execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .lifecycle_sizing import lifecycle_risk_fraction, resolve_lifecycle_sizing
from .models import Decision, DecisionStatus, InstrumentSelected
from .paper_runtime import PaperRuntimeError, process_paper_event
from .pine_paper_orchestrator import (
    PinePaperExecutionError,
    _all_open_trades,
    _aware,
    _execution_result,
    _paper_risk_state,
    _required_text,
    _signal_payload,
)
from .pine_paper_reconciliation import (
    ReconciledAwsPinePaperExecutor,
    _result,
    prepare_armed_replay,
)
from .portfolio import PortfolioDataStatus, PortfolioSnapshot
from .reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor
from .risk import PortfolioRiskEngine, PortfolioRiskState, ProposedTradeRisk
from .sectors import is_verified_sector, resolve_sector


STOCK_PRIMARY_POLICY = "STOCK_PRIMARY_MODEL_VALIDATION_V1"
MIN_STOCK_PRICE = 10.0


class StockPrimaryReceiptReconciledAwsPinePaperExecutor(
    ReceiptReconciledAwsPinePaperExecutor
):
    """Open only stock PAPER positions while preserving legacy option management."""

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        before_trade = self._before_trade(ingress)
        self._receipt_quote = None
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
        self._receipt_quote = None
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
            lifecycle = resolve_lifecycle_sizing(ingress.get("lifecycle"))
            if lifecycle is not None and not lifecycle.entry_allowed:
                return _execution_result(
                    disposition="NO_TRADE",
                    reason="LIFECYCLE_EXTENDED_NO_CHASE",
                    action=action,
                    symbol=symbol,
                    context=_policy_context(),
                )
            sector = resolve_sector(symbol, str(ingress.get("sector", "")))
            if not is_verified_sector(sector):
                return _execution_result(
                    disposition="NO_TRADE",
                    reason="SECTOR_DATA_UNVERIFIED",
                    action=action,
                    symbol=symbol,
                    context=_policy_context(),
                )
            return self._stock_entry(ingress, now=now)

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

        # No new options can be opened. If an old option position exists, retain
        # the prior fail-closed quote/reconciliation path solely to manage it.
        if open_trades[0].instrument == InstrumentSelected.OPTION:
            result = ReconciledAwsPinePaperExecutor.execute(self, ingress, now=now)
            context = dict(result.get("context") or {})
            context.update(
                {
                    **_policy_context(),
                    "legacy_option_position_management": True,
                }
            )
            result["context"] = context
            return result

        result = self._runner(ingress, now)
        context = dict(result.get("context") or {})
        context.update(_policy_context())
        result["context"] = context
        return result

    def _stock_entry(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()
        sector = resolve_sector(symbol, str(ingress.get("sector", "")))
        if not is_verified_sector(sector):
            return _execution_result(
                disposition="NO_TRADE",
                reason="SECTOR_DATA_UNVERIFIED",
                action="ENTRY_LONG",
                symbol=symbol,
                context=_policy_context(),
            )
        if self.ledger.find_open(symbol):
            return _execution_result(
                disposition="NO_TRADE",
                reason="OPEN_POSITION_ALREADY_EXISTS",
                action="ENTRY_LONG",
                symbol=symbol,
                context=_policy_context(),
            )

        try:
            price = float(ingress["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PinePaperExecutionError("STOCK_SIGNAL_PRICE_INVALID") from exc
        if price < MIN_STOCK_PRICE:
            return _execution_result(
                disposition="NO_TRADE",
                reason="STOCK_PRICE_BELOW_CANONICAL_FLOOR",
                action="ENTRY_LONG",
                symbol=symbol,
                context={**_policy_context(), "minimum_stock_price": MIN_STOCK_PRICE},
            )

        try:
            stock_stop = float(ingress["stock_stop_price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PinePaperExecutionError("STOCK_STOP_CONTEXT_REQUIRED") from exc
        if stock_stop <= 0 or stock_stop >= price:
            return _execution_result(
                disposition="NO_TRADE",
                reason="STOCK_STOP_INVALID_FOR_LONG_ENTRY",
                action="ENTRY_LONG",
                symbol=symbol,
                context={**_policy_context(), "signal_price": price, "stock_stop": stock_stop},
            )

        open_trades = _all_open_trades(self.ledger)
        total_risk, daily_risk, new_today, cluster_risk, sector_risk = (
            _paper_risk_state(open_trades, now=now)
        )
        approved_risk_fraction = 0.005
        lifecycle_fraction = lifecycle_risk_fraction(
            ingress.get("lifecycle"), approved_risk_fraction
        )
        proposed_loss = self.paper_nav * lifecycle_fraction

        snapshot = PortfolioSnapshot.create(
            snapshot_id=f"paper-{int(now.timestamp())}",
            account_id=getattr(self.ledger, "account_id", "paper-staging"),
            source="DAILY_ALPHA_DYNAMODB_PAPER_LEDGER",
            as_of=now.isoformat(),
            cash=self.paper_nav,
            buying_power=self.paper_nav,
            positions=(),
            data_status=PortfolioDataStatus.AVAILABLE,
        )
        risk_state = PortfolioRiskState(
            daily_new_risk=daily_risk,
            new_positions_today=new_today,
            daily_loss=0.0,
            weekly_drawdown=0.0,
            rolling_drawdown=0.0,
            total_risk=total_risk,
            beta_exposure=0.0,
            delta_exposure=0.0,
            cluster_risk=tuple((str(name), float(value)) for name, value in cluster_risk),
            sector_risk=tuple((str(name), float(value)) for name, value in sector_risk),
        )
        proposed = ProposedTradeRisk(
            decision_id=str(ingress.get("signal_id", "")),
            symbol=symbol,
            planned_loss=proposed_loss,
            cluster_id=symbol,
            sector=sector,
            beta_exposure=0.0,
            delta_exposure=0.0,
            event_risk=False,
            liquidity_score=1.0,
        )
        risk_decision = PortfolioRiskEngine().evaluate(
            snapshot=snapshot,
            state=risk_state,
            proposed=proposed,
        )
        risk_payload = risk_decision.to_dict()
        if not risk_decision.approved:
            return _execution_result(
                disposition="NO_TRADE",
                reason="PORTFOLIO_RISK_GATE_FAILED",
                action="ENTRY_LONG",
                symbol=symbol,
                context={
                    **_policy_context(),
                    "risk": risk_payload,
                },
            )

        decision = Decision.create(
            symbol=symbol,
            status=DecisionStatus.SELECTED,
            instrument_selected=InstrumentSelected.STOCK,
            fallback_reason=STOCK_PRIMARY_POLICY,
        )
        decision_payload = decision.to_dict()
        engine_result = {
            "ok": True,
            "mode": "PAPER",
            "live_trading_enabled": False,
            "signal": _signal_payload(ingress),
            "risk": risk_payload,
            "decision": decision_payload,
        }

        try:
            paper = process_paper_event(
                {
                    "operation": "OPEN_FROM_DECISION",
                    "engine_result": engine_result,
                    "pricing": {
                        "stock_price": price,
                        "stock_stop_price": stock_stop,
                    },
                    "sizing": {"risk_per_trade_pct": lifecycle_fraction},
                },
                self.ledger,
                now=now,
            )
        except (PaperRuntimeError, ValueError) as exc:
            raise PinePaperExecutionError(f"PAPER_ENTRY_FAILED:{exc}") from exc

        return _execution_result(
            disposition="EXECUTED_PAPER",
            reason="PAPER_STOCK_POSITION_OPENED",
            action="ENTRY_LONG",
            symbol=symbol,
            paper=paper,
            context={
                **_policy_context(),
                "risk": risk_payload,
                "decision": decision_payload,
                "signal_fill_price": price,
                "stock_stop_price": stock_stop,
            },
        )

    def _replay_stock_primary(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        action = str(ingress.get("action", "")).upper()
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()
        if action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
            raise PinePaperExecutionError("PINE_ACTION_UNSUPPORTED")

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

        if open_trades and open_trades[0].instrument == InstrumentSelected.OPTION:
            result = ReconciledAwsPinePaperExecutor.replay_armed(self, ingress, now=now)
            context = dict(result.get("context") or {})
            context.update(
                {
                    **_policy_context(),
                    "legacy_option_position_management": True,
                }
            )
            result["context"] = context
            return result

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


def _policy_context() -> dict[str, Any]:
    return {
        "execution_policy": STOCK_PRIMARY_POLICY,
        "new_entry_instrument": InstrumentSelected.STOCK.value,
        "options_execution_enabled": False,
        "orats_required_for_new_entry": False,
        "fill_model": "CONFIRMED_SIGNAL_PRICE_PROCESS_ORDERS_ON_CLOSE",
        "research_options_intelligence_enabled": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
