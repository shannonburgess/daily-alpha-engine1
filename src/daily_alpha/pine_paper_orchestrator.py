"""Stock-only PAPER execution orchestration for validated Pine events.

The automated Daily Alpha execution path opens and manages STOCK positions only.
Options are user-directed and broker-chain sourced; this module never fetches an
option chain and never manages an option position autonomously.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from .dynamo_ledger import DynamoPaperLedger, _trade_from_json
from .ledger import PaperTrade
from .lifecycle_sizing import lifecycle_risk_fraction, resolve_lifecycle_sizing
from .models import Decision, DecisionStatus, InstrumentSelected
from .paper_runtime import PaperRuntimeError, process_paper_event
from .portfolio import PortfolioDataStatus, PortfolioSnapshot
from .risk import PortfolioRiskEngine, PortfolioRiskState, ProposedTradeRisk
from .sectors import is_verified_sector, resolve_sector

STOCK_PRIMARY_POLICY = "STOCK_PRIMARY_MODEL_VALIDATION_V1"
MIN_STOCK_PRICE = 10.0


class PinePaperExecutionError(RuntimeError):
    """Raised when a validated Pine event cannot be executed safely in PAPER."""


class AwsPinePaperExecutor:
    """Apply validated STOCK-only Pine events to the PAPER ledger."""

    def __init__(
        self,
        *,
        ledger: Any | None = None,
        paper_nav: float | None = None,
    ) -> None:
        self.ledger = ledger or DynamoPaperLedger()
        self.paper_nav = paper_nav if paper_nav is not None else _paper_nav_from_env()
        if self.paper_nav <= 0:
            raise PinePaperExecutionError("PAPER_NAV_MUST_BE_POSITIVE")

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        action = str(ingress.get("action", "")).upper()
        if action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
            raise PinePaperExecutionError("PINE_ACTION_UNSUPPORTED")
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()

        if not _regular_execution_window(timestamp):
            return _execution_result(
                disposition="NO_TRADE",
                reason="OUTSIDE_REGULAR_EXECUTION_WINDOW",
                action=action,
                symbol=symbol,
                context=_stock_policy_context(),
            )
        if action == "ENTRY_LONG":
            return self._entry(ingress, timestamp)
        return self._runner(ingress, timestamp)

    def _entry(self, ingress: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()
        lifecycle = resolve_lifecycle_sizing(ingress.get("lifecycle"))
        if lifecycle is not None and not lifecycle.entry_allowed:
            return _execution_result(
                disposition="NO_TRADE",
                reason="LIFECYCLE_EXTENDED_NO_CHASE",
                action="ENTRY_LONG",
                symbol=symbol,
                context=_stock_policy_context(),
            )
        sector = resolve_sector(symbol, str(ingress.get("sector", "")))
        if not is_verified_sector(sector):
            return _execution_result(
                disposition="NO_TRADE",
                reason="SECTOR_DATA_UNVERIFIED",
                action="ENTRY_LONG",
                symbol=symbol,
                context=_stock_policy_context(),
            )
        if self.ledger.find_open(symbol):
            return _execution_result(
                disposition="NO_TRADE",
                reason="OPEN_POSITION_ALREADY_EXISTS",
                action="ENTRY_LONG",
                symbol=symbol,
                context=_stock_policy_context(),
            )

        price = _required_positive_float(ingress.get("price"), "price")
        if price < MIN_STOCK_PRICE:
            return _execution_result(
                disposition="NO_TRADE",
                reason="STOCK_PRICE_BELOW_CANONICAL_FLOOR",
                action="ENTRY_LONG",
                symbol=symbol,
                context={**_stock_policy_context(), "minimum_stock_price": MIN_STOCK_PRICE},
            )
        stop = _required_positive_float(
            ingress.get("stock_stop_price"), "stock_stop_price"
        )
        if stop >= price:
            return _execution_result(
                disposition="NO_TRADE",
                reason="STOCK_STOP_INVALID_FOR_LONG_ENTRY",
                action="ENTRY_LONG",
                symbol=symbol,
                context={**_stock_policy_context(), "signal_price": price, "stock_stop": stop},
            )

        open_trades = _all_open_trades(self.ledger)
        total_risk, daily_risk, new_today, cluster_risk, sector_risk = _paper_risk_state(
            open_trades, now=now
        )
        approved_risk_fraction = 0.005
        lifecycle_fraction = lifecycle_risk_fraction(
            ingress.get("lifecycle"), approved_risk_fraction
        )
        proposed_loss = self.paper_nav * lifecycle_fraction

        snapshot = PortfolioSnapshot.create(
            snapshot_id=f"paper-{int(now.timestamp())}",
            account_id=getattr(self.ledger, "account_id", "paper-staging"),
            source="DAILY_ALPHA_PAPER_LEDGER",
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
                context={**_stock_policy_context(), "risk": risk_payload},
            )

        decision = Decision.create(
            symbol=symbol,
            status=DecisionStatus.SELECTED,
            instrument_selected=InstrumentSelected.STOCK,
            fallback_reason=STOCK_PRIMARY_POLICY,
        )
        signal_payload = _signal_payload(ingress)
        signal_payload["received_at"] = str(ingress.get("received_at") or now.isoformat())
        engine_result = {
            "ok": True,
            "mode": "PAPER",
            "live_trading_enabled": False,
            "signal": signal_payload,
            "risk": risk_payload,
            "decision": decision.to_dict(),
        }
        try:
            paper = process_paper_event(
                {
                    "operation": "OPEN_FROM_DECISION",
                    "engine_result": engine_result,
                    "pricing": {
                        "stock_price": price,
                        "stock_stop_price": stop,
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
                **_stock_policy_context(),
                "risk": risk_payload,
                "decision": decision.to_dict(),
                "signal_fill_price": price,
                "stock_stop_price": stop,
            },
        )

    def _runner(self, ingress: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()
        action = _required_text(ingress.get("action"), "action").upper()
        open_trades = self.ledger.find_open(symbol)
        if not open_trades:
            return _execution_result(
                disposition="NO_TRADE",
                reason="NO_OPEN_POSITION",
                action=action,
                symbol=symbol,
                context=_stock_policy_context(),
            )
        if len(open_trades) != 1:
            raise PinePaperExecutionError("MULTIPLE_OPEN_INSTRUMENTS_FOR_SYMBOL")
        trade = open_trades[0]
        if trade.instrument != InstrumentSelected.STOCK:
            return _execution_result(
                disposition="NO_TRADE",
                reason="USER_DIRECTED_OPTION_MANAGEMENT_REQUIRED",
                action=action,
                symbol=symbol,
                context={
                    **_stock_policy_context(),
                    "automated_option_management": False,
                },
            )

        price = _required_positive_float(ingress.get("price"), "price")
        if action == "ADD" and price <= trade.entry_price:
            return _execution_result(
                disposition="NO_TRADE",
                reason="ADD_REJECTED_POSITION_NOT_PROFITABLE",
                action=action,
                symbol=symbol,
                context=_stock_policy_context(),
            )
        pricing: dict[str, float] = {}
        if action in {"ADD", "PARTIAL"}:
            pricing["stock_fill_price"] = price
        else:
            pricing["stock_exit_price"] = price
        operation = {
            "ADD": "ADD_FROM_SIGNAL",
            "PARTIAL": "PARTIAL_FROM_SIGNAL",
            "EXIT": "CLOSE_FROM_SIGNAL",
        }[action]
        try:
            paper = process_paper_event(
                {
                    "operation": operation,
                    "signal": _signal_payload(ingress),
                    "pricing": pricing,
                },
                self.ledger,
                now=now,
            )
        except (PaperRuntimeError, ValueError) as exc:
            raise PinePaperExecutionError(f"PAPER_RUNNER_FAILED:{exc}") from exc
        return _execution_result(
            disposition="EXECUTED_PAPER",
            reason=f"PAPER_{action}_APPLIED",
            action=action,
            symbol=symbol,
            paper=paper,
            context=_stock_policy_context(),
        )


def _regular_execution_window(value: datetime) -> bool:
    local = _aware(value).astimezone(ZoneInfo("America/New_York"))
    if local.weekday() >= 5:
        return False
    clock = local.time().replace(tzinfo=None)
    return time(9, 30) <= clock < time(16, 0)


def _paper_nav_from_env() -> float:
    raw = os.getenv("DAILY_ALPHA_PAPER_NAV", "").strip()
    if not raw:
        raise PinePaperExecutionError("DAILY_ALPHA_PAPER_NAV_NOT_CONFIGURED")
    try:
        return float(raw)
    except ValueError as exc:
        raise PinePaperExecutionError("DAILY_ALPHA_PAPER_NAV_INVALID") from exc


def _all_open_trades(ledger: Any) -> list[PaperTrade]:
    if not isinstance(ledger, DynamoPaperLedger):
        helper = getattr(ledger, "list_open_all", None)
        return list(helper()) if callable(helper) else []

    prefix = f"ACCOUNT#{ledger.account_id}#POSITION#"
    kwargs: dict[str, Any] = {
        "TableName": ledger.table_name,
        "FilterExpression": "begins_with(pk, :prefix) AND #sk = :open",
        "ExpressionAttributeNames": {"#sk": "sk"},
        "ExpressionAttributeValues": {
            ":prefix": {"S": prefix},
            ":open": {"S": "OPEN"},
        },
    }
    results: list[PaperTrade] = []
    while True:
        try:
            response = ledger.client.scan(**kwargs)
        except Exception as exc:
            raise PinePaperExecutionError("PAPER_LEDGER_SCAN_FAILED") from exc
        for item in response.get("Items", []):
            raw = item.get("trade_json", {}).get("S")
            if raw:
                results.append(_trade_from_json(raw))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return results


def _paper_risk_state(
    trades: list[PaperTrade],
    *,
    now: datetime,
) -> tuple[float, float, int, list[list[Any]], list[list[Any]]]:
    total = 0.0
    daily = 0.0
    new_today = 0
    by_symbol: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for trade in trades:
        multiplier = 100 if trade.instrument == InstrumentSelected.OPTION else 1
        amount = trade.quantity * trade.entry_price * multiplier
        total += amount
        by_symbol[trade.symbol] = by_symbol.get(trade.symbol, 0.0) + amount
        by_sector[trade.sector] = by_sector.get(trade.sector, 0.0) + amount
        try:
            entered = _aware(datetime.fromisoformat(trade.entry_time))
        except ValueError:
            continue
        if entered.date() == now.date():
            daily += amount
            new_today += 1
    clusters = [[symbol, amount] for symbol, amount in sorted(by_symbol.items())]
    sectors = [[sector, amount] for sector, amount in sorted(by_sector.items())]
    return total, daily, new_today, clusters, sectors


def _signal_payload(ingress: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "signal_id": ingress.get("signal_id"),
        "symbol": ingress.get("symbol"),
        "action": ingress.get("action"),
        "strategy": ingress.get("strategy"),
        "strategy_version": ingress.get("strategy_version"),
        "timeframe": ingress.get("timeframe"),
        "price": ingress.get("price"),
        "bar_time": ingress.get("bar_time"),
    }
    if ingress.get("position_fraction") is not None:
        payload["position_fraction"] = ingress.get("position_fraction")
    if ingress.get("runner_stage") is not None:
        payload["runner_stage"] = ingress.get("runner_stage")
    return payload


def _execution_result(
    *,
    disposition: str,
    reason: str,
    action: str,
    symbol: str,
    paper: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "reason": reason,
        "action": action,
        "symbol": symbol,
        "paper_execution_triggered": disposition == "EXECUTED_PAPER",
        "paper_ledger_updated": bool(paper and paper.get("paper_ledger_updated") is True),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "paper": dict(paper or {}),
        "context": dict(context or {}),
    }


def _stock_policy_context() -> dict[str, Any]:
    return {
        "execution_policy": STOCK_PRIMARY_POLICY,
        "new_entry_instrument": "STOCK",
        "automated_options_execution": False,
        "options_mode": "USER_DIRECTED_BROKER_CHAIN",
        "fill_model": "CONFIRMED_SIGNAL_PRICE_PROCESS_ORDERS_ON_CLOSE",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PinePaperExecutionError(f"{name} is required")
    return text


def _required_positive_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PinePaperExecutionError(f"{name} must be numeric") from exc
    if number <= 0:
        raise PinePaperExecutionError(f"{name} must be positive")
    return number


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
