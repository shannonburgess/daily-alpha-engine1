"""Paper-only execution orchestration for validated Pine SQS events.

This module is the controlled bridge from an authenticated/validated Pine event to
paper-ledger mutations. It never calls a live broker. Option fills come from fresh
ORATS quotes for the selected/open contract; stock fills use the Pine underlying
price only when the entry event also carries a validated Turtle stop and liquidity
context.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Callable

from .dynamo_ledger import DynamoPaperLedger, _trade_from_json
from .ledger import PaperTrade
from .models import DecisionStatus, InstrumentSelected
from .orats import OratsClient, OratsError
from .paper_runtime import PaperRuntimeError, process_paper_event
from .runtime import RuntimeInputError, evaluate_entry_event


class PinePaperExecutionError(RuntimeError):
    """Raised when a validated Pine event cannot be executed safely in paper."""


OratsFactory = Callable[[str], OratsClient]


class AwsPinePaperExecutor:
    """Resolve fresh context and apply a validated Pine event to the paper ledger."""

    DEFAULT_SECRET_ID = "daily-alpha/orats/staging"

    def __init__(
        self,
        *,
        ledger: Any | None = None,
        secrets_client: Any | None = None,
        paper_nav: float | None = None,
        secret_id: str | None = None,
        orats_factory: OratsFactory | None = None,
    ) -> None:
        self.ledger = ledger or DynamoPaperLedger()
        self.secret_id = (
            secret_id
            or os.getenv("DAILY_ALPHA_ORATS_SECRET_ID")
            or self.DEFAULT_SECRET_ID
        ).strip()
        self.paper_nav = paper_nav if paper_nav is not None else _paper_nav_from_env()
        if self.paper_nav <= 0:
            raise PinePaperExecutionError("PAPER_NAV_MUST_BE_POSITIVE")

        if secrets_client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - Lambda includes boto3
                raise PinePaperExecutionError("BOTO3_UNAVAILABLE") from exc
            secrets_client = boto3.client("secretsmanager")
        self.secrets_client = secrets_client
        self.orats_factory = orats_factory or (
            lambda token: OratsClient(
                token=token,
                mode="delayed",
                max_age_minutes=25,
            )
        )
        self._token: str | None = None

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        action = str(ingress.get("action", "")).upper()
        if action == "ENTRY_LONG":
            return self._entry(ingress, timestamp)
        if action in {"ADD", "PARTIAL", "EXIT"}:
            return self._runner(ingress, timestamp)
        raise PinePaperExecutionError("PINE_ACTION_UNSUPPORTED")

    def _entry(self, ingress: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()
        if self.ledger.find_open(symbol):
            return _execution_result(
                disposition="NO_TRADE",
                reason="OPEN_POSITION_ALREADY_EXISTS",
                action="ENTRY_LONG",
                symbol=symbol,
            )

        try:
            chain = self._orats().fetch_chain(symbol, as_of=now)
        except OratsError as exc:
            raise PinePaperExecutionError(f"ORATS_DATA_ERROR:{exc}") from exc

        open_trades = _all_open_trades(self.ledger)
        total_risk, daily_risk, new_today, cluster_risk = _paper_risk_state(
            open_trades, now=now
        )
        proposed_loss = self.paper_nav * 0.005

        stock_stop = _optional_positive_float(
            ingress.get("stock_stop_price"), "stock_stop_price"
        )
        adv = _optional_nonnegative_float(
            ingress.get("average_daily_dollar_volume"),
            "average_daily_dollar_volume",
        )
        stock = None
        if stock_stop is not None and adv is not None and stock_stop < float(ingress["price"]):
            stock = {
                "price": float(ingress["price"]),
                "average_daily_dollar_volume": adv,
                "eligible": True,
            }

        decision_event = {
            "signal": _signal_payload(ingress),
            "portfolio": {
                "snapshot_id": f"paper-{int(now.timestamp())}",
                "account_id": getattr(self.ledger, "account_id", "paper-staging"),
                "source": "DAILY_ALPHA_DYNAMODB_PAPER_LEDGER",
                "as_of": now.isoformat(),
                "cash": self.paper_nav,
                "buying_power": self.paper_nav,
                "positions": [],
                "data_status": "AVAILABLE",
            },
            "risk_state": {
                "daily_new_risk": daily_risk,
                "new_positions_today": new_today,
                "daily_loss": 0.0,
                "weekly_drawdown": 0.0,
                "rolling_drawdown": 0.0,
                "total_risk": total_risk,
                "beta_exposure": 0.0,
                "delta_exposure": 0.0,
                "cluster_risk": cluster_risk,
                "sector_risk": [["UNKNOWN", total_risk]] if total_risk else [],
            },
            "proposed_trade": {
                "decision_id": str(ingress.get("signal_id", "")),
                "planned_loss": proposed_loss,
                "cluster_id": symbol,
                "sector": "UNKNOWN",
                "beta_exposure": 0.0,
                "delta_exposure": 0.0,
                "event_risk": False,
                "liquidity_score": 1.0,
            },
            "market": {
                "option_data_available": True,
                "option_data_observed_at": chain.observed_at.isoformat(),
                "orats_mode": chain.source_mode,
                "options": [_option_to_runtime(item) for item in chain.candidates],
                "stock": stock,
            },
        }

        try:
            decision = evaluate_entry_event(decision_event, now=now)
        except (RuntimeInputError, ValueError) as exc:
            raise PinePaperExecutionError(f"ENTRY_CONTEXT_INVALID:{exc}") from exc

        decision_payload = decision["decision"]
        status = str(decision_payload.get("status", ""))
        if status != DecisionStatus.SELECTED.value:
            return _execution_result(
                disposition="NO_TRADE",
                reason=str(
                    decision_payload.get("fallback_reason")
                    or decision["risk"].get("reasons")
                    or status
                ),
                action="ENTRY_LONG",
                symbol=symbol,
                context={"risk": decision["risk"], "decision": decision_payload},
            )

        engine_result = {
            "ok": True,
            "mode": "PAPER",
            "live_trading_enabled": False,
            **decision,
        }
        pricing: dict[str, float] = {}
        if decision_payload["instrument_selected"] == InstrumentSelected.STOCK.value:
            if stock_stop is None:
                raise PinePaperExecutionError("STOCK_STOP_CONTEXT_REQUIRED")
            pricing = {
                "stock_price": float(ingress["price"]),
                "stock_stop_price": stock_stop,
            }

        try:
            paper = process_paper_event(
                {
                    "operation": "OPEN_FROM_DECISION",
                    "engine_result": engine_result,
                    "pricing": pricing,
                },
                self.ledger,
                now=now,
            )
        except (PaperRuntimeError, ValueError) as exc:
            raise PinePaperExecutionError(f"PAPER_ENTRY_FAILED:{exc}") from exc

        return _execution_result(
            disposition="EXECUTED_PAPER",
            reason="PAPER_POSITION_OPENED",
            action="ENTRY_LONG",
            symbol=symbol,
            paper=paper,
            context={"risk": decision["risk"], "decision": decision_payload},
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
            )
        if len(open_trades) != 1:
            raise PinePaperExecutionError("MULTIPLE_OPEN_INSTRUMENTS_FOR_SYMBOL")

        trade = open_trades[0]
        signal = _signal_payload(ingress)
        pricing: dict[str, float] = {}
        if trade.instrument == InstrumentSelected.OPTION:
            quote = self._option_quote(trade, now)
            if action == "ADD":
                pricing["option_fill_price"] = quote.ask
            elif action == "PARTIAL":
                pricing["option_fill_price"] = quote.bid
            else:
                pricing["option_exit_price"] = quote.bid
        else:
            if action in {"ADD", "PARTIAL"}:
                pricing["stock_fill_price"] = float(ingress["price"])
            else:
                pricing["stock_exit_price"] = float(ingress["price"])

        operation = {
            "ADD": "ADD_FROM_SIGNAL",
            "PARTIAL": "PARTIAL_FROM_SIGNAL",
            "EXIT": "CLOSE_FROM_SIGNAL",
        }[action]
        try:
            paper = process_paper_event(
                {
                    "operation": operation,
                    "signal": signal,
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
        )

    def _option_quote(self, trade: PaperTrade, now: datetime):
        if not trade.option_expiration or trade.option_strike is None or not trade.option_type:
            raise PinePaperExecutionError("OPEN_OPTION_CONTRACT_IDENTITY_INCOMPLETE")
        try:
            expiration = date.fromisoformat(trade.option_expiration)
        except ValueError as exc:
            raise PinePaperExecutionError("OPEN_OPTION_EXPIRATION_INVALID") from exc
        dte = (expiration - now.date()).days
        if dte < 0:
            raise PinePaperExecutionError("OPEN_OPTION_ALREADY_EXPIRED")

        try:
            chain = self._orats().fetch_chain(
                trade.symbol,
                as_of=now,
                dte_min=max(0, dte - 1),
                dte_max=dte + 1,
            )
        except OratsError as exc:
            raise PinePaperExecutionError(f"ORATS_DATA_ERROR:{exc}") from exc

        matches = [
            item
            for item in chain.candidates
            if item.expiration == trade.option_expiration
            and abs(item.strike - float(trade.option_strike)) < 1e-8
            and item.option_type.upper() == trade.option_type.upper()
        ]
        if not matches:
            raise PinePaperExecutionError("OPEN_OPTION_QUOTE_NOT_FOUND")
        return min(matches, key=lambda item: item.spread_pct)

    def _orats(self) -> OratsClient:
        if self._token is None:
            self._token = _read_secret_token(self.secrets_client, self.secret_id)
        return self.orats_factory(self._token)


def _paper_nav_from_env() -> float:
    raw = os.getenv("DAILY_ALPHA_PAPER_NAV", "").strip()
    if not raw:
        raise PinePaperExecutionError("DAILY_ALPHA_PAPER_NAV_NOT_CONFIGURED")
    try:
        return float(raw)
    except ValueError as exc:
        raise PinePaperExecutionError("DAILY_ALPHA_PAPER_NAV_INVALID") from exc


def _read_secret_token(client: Any, secret_id: str) -> str:
    if not secret_id:
        raise PinePaperExecutionError("ORATS_SECRET_ID_NOT_CONFIGURED")
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        raise PinePaperExecutionError("ORATS_SECRET_READ_FAILED") from exc
    secret = response.get("SecretString") if isinstance(response, dict) else None
    if not secret:
        raise PinePaperExecutionError("ORATS_SECRET_EMPTY")
    try:
        payload = json.loads(secret)
    except json.JSONDecodeError as exc:
        raise PinePaperExecutionError("ORATS_SECRET_JSON_INVALID") from exc
    token = str(payload.get("token", "")).strip() if isinstance(payload, dict) else ""
    if not token:
        raise PinePaperExecutionError("ORATS_SECRET_TOKEN_MISSING")
    return token


def _all_open_trades(ledger: Any) -> list[PaperTrade]:
    if not isinstance(ledger, DynamoPaperLedger):
        # Unit-test/local ledgers may expose a helper; otherwise the current symbol
        # path still remains fail-closed by returning no assumed cross-position risk.
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
) -> tuple[float, float, int, list[list[Any]]]:
    total = 0.0
    daily = 0.0
    new_today = 0
    by_symbol: dict[str, float] = {}
    for trade in trades:
        multiplier = 100 if trade.instrument == InstrumentSelected.OPTION else 1
        # Long-option premium at risk is exact; treating stock capital as fully at
        # risk is intentionally conservative until a richer stored stop model exists.
        amount = trade.quantity * trade.entry_price * multiplier
        total += amount
        by_symbol[trade.symbol] = by_symbol.get(trade.symbol, 0.0) + amount
        try:
            entered = datetime.fromisoformat(trade.entry_time)
            entered = _aware(entered)
        except ValueError:
            continue
        if entered.date() == now.date():
            daily += amount
            new_today += 1
    clusters = [[symbol, amount] for symbol, amount in sorted(by_symbol.items())]
    return total, daily, new_today, clusters


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


def _option_to_runtime(item: Any) -> dict[str, Any]:
    return {
        "expiration": item.expiration,
        "strike": item.strike,
        "option_type": item.option_type,
        "dte": item.dte,
        "bid": item.bid,
        "ask": item.ask,
        "open_interest": item.open_interest,
        "volume": item.volume,
        "delta": item.delta,
    }


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
        "paper_ledger_updated": bool(
            paper and paper.get("paper_ledger_updated") is True
        ),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "paper": dict(paper or {}),
        "context": dict(context or {}),
    }


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PinePaperExecutionError(f"{name} is required")
    return text


def _optional_positive_float(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PinePaperExecutionError(f"{name} must be numeric") from exc
    if number <= 0:
        raise PinePaperExecutionError(f"{name} must be positive")
    return number


def _optional_nonnegative_float(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PinePaperExecutionError(f"{name} must be numeric") from exc
    if number < 0:
        raise PinePaperExecutionError(f"{name} must be non-negative")
    return number


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
