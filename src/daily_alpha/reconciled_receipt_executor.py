"""Reconciled stock-primary PAPER executor with exact lifecycle receipts.

New Daily Alpha PAPER positions are shares only. The confirmed Pine/scanner signal
price is the model-validation fill so option-chain selection cannot obscure whether
the signal model has edge. The existing after-hours ARMED/replay control loop is
preserved: an after-hours event is persisted first and the scheduled replay worker
applies the stock decision during a regular execution window. ORATS is not read for
new stock entries. It remains available only for research and for fail-closed
management of a legacy OPTION PAPER position.

This module never enables live brokerage execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .execution_receipts import build_paper_execution_receipt
from .lifecycle_sizing import lifecycle_risk_fraction, resolve_lifecycle_sizing
from .models import Decision, DecisionStatus, InstrumentSelected
from .paper_runtime import PaperRuntimeError, process_paper_event
from .pine_paper_orchestrator import (
    PinePaperExecutionError,
    _all_open_trades,
    _aware,
    _execution_result,
    _paper_risk_state,
    _regular_execution_window,
    _required_text,
    _signal_payload,
)
from .pine_paper_reconciliation import (
    ReconciledAwsPinePaperExecutor,
    _result,
    prepare_armed_replay,
)
from .portfolio import PortfolioDataStatus, PortfolioSnapshot
from .risk import PortfolioRiskEngine, PortfolioRiskState, ProposedTradeRisk
from .sectors import is_verified_sector, resolve_sector

STOCK_PRIMARY_POLICY = "STOCK_PRIMARY_MODEL_VALIDATION_V1"
MIN_STOCK_PRICE = 10.0


class ReceiptReconciledAwsPinePaperExecutor(ReconciledAwsPinePaperExecutor):
    """Canonical PAPER executor: new positions are stock only."""

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
            if not _regular_execution_window(now):
                return _result(
                    disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                    reason="MARKET_CLOSED_REVALIDATION_REQUIRED",
                    action=action,
                    symbol=symbol,
                    context={
                        **_policy_context(),
                        "armed": True,
                        "armed_at": now.isoformat(),
                        "signal_id": str(ingress.get("signal_id", "")),
                        "revalidation_required": True,
                        "refresh_portfolio_risk": True,
                        "refresh_no_chase": True,
                        "model_validation_fill_price": _positive_float_or_none(
                            ingress.get("price")
                        ),
                    },
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

        if not _regular_execution_window(now):
            return _result(
                disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                reason="MARKET_CLOSED_RUNNER_REVALIDATION_REQUIRED",
                action=action,
                symbol=symbol,
                context={
                    **_policy_context(),
                    "armed": True,
                    "armed_at": now.isoformat(),
                    "signal_id": str(ingress.get("signal_id", "")),
                    "runner_stage": ingress.get("runner_stage"),
                    "revalidation_required": True,
                    "model_validation_fill_price": _positive_float_or_none(
                        ingress.get("price")
                    ),
                },
            )

        instrument = _trade_instrument(open_trades[0])
        if instrument == InstrumentSelected.OPTION:
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
        if instrument != InstrumentSelected.STOCK:
            raise PinePaperExecutionError("OPEN_PAPER_INSTRUMENT_INVALID")

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
                context={
                    **_policy_context(),
                    "minimum_stock_price": MIN_STOCK_PRICE,
                },
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
                context={
                    **_policy_context(),
                    "signal_price": price,
                    "stock_stop": stock_stop,
                },
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
            cluster_risk=tuple(
                (str(name), float(value)) for name, value in cluster_risk
            ),
            sector_risk=tuple(
                (str(name), float(value)) for name, value in sector_risk
            ),
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
                context={**_policy_context(), "risk": risk_payload},
            )

        decision = Decision.create(
            symbol=symbol,
            status=DecisionStatus.SELECTED,
            instrument_selected=InstrumentSelected.STOCK,
            fallback_reason=STOCK_PRIMARY_POLICY,
        )
        decision_payload = decision.to_dict()
        signal_payload = _signal_payload(ingress)
        signal_payload["received_at"] = str(
            ingress.get("received_at") or now.isoformat()
        )
        engine_result = {
            "ok": True,
            "mode": "PAPER",
            "live_trading_enabled": False,
            "signal": signal_payload,
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

        if open_trades and _trade_instrument(open_trades[0]) == InstrumentSelected.OPTION:
            result = ReconciledAwsPinePaperExecutor.replay_armed(
                self,
                ingress,
                now=now,
            )
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
            initial_risk_basis=_persisted_initial_risk(paper, before_trade)
            or _initial_risk_from_result(result),
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
                self._receipt_quote.ask
                if action == "ADD"
                else self._receipt_quote.bid
            )
        if instrument == InstrumentSelected.STOCK.value:
            context = result.get("context")
            if isinstance(context, Mapping):
                replay_price = _positive_float_or_none(
                    context.get("model_validation_fill_price")
                    or context.get("replay_market_price")
                )
                if replay_price is not None:
                    return replay_price
            return float(ingress["price"])
        raise ValueError("EXECUTION_RECEIPT_INSTRUMENT_INVALID")


def _trade_instrument(trade: Any) -> InstrumentSelected:
    raw = getattr(trade, "instrument", None)
    if raw is None and hasattr(trade, "to_dict"):
        payload = trade.to_dict()
        if isinstance(payload, Mapping):
            raw = payload.get("instrument")
    if isinstance(raw, InstrumentSelected):
        return raw
    try:
        return InstrumentSelected(str(raw).upper())
    except ValueError as exc:
        raise PinePaperExecutionError("OPEN_PAPER_INSTRUMENT_INVALID") from exc


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
    if (
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], Mapping)
    ):
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
