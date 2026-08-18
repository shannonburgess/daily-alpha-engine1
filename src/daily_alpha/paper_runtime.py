"""Fail-closed paper-trading runtime that consumes approved engine decisions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .models import (
    Decision,
    DecisionStatus,
    InstrumentSelected,
    OptionCandidate,
)
from .pipeline import EntryPricing, PaperTradingPipeline
from .sectors import is_verified_sector, resolve_sector
from .signals import SignalAction, parse_pine_signal
from .sizing import PortfolioLimits


class PaperRuntimeError(ValueError):
    """Raised when a paper-trading event is incomplete or violates safety gates."""


def process_paper_event(
    event: Mapping[str, Any],
    ledger: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Open, adjust, close, or inspect paper positions without live execution."""
    operation = str(event.get("operation", "")).strip().upper()
    if operation == "OPEN_FROM_DECISION":
        return _open_from_decision(event, ledger)
    if operation == "ADD_FROM_SIGNAL":
        return _runner_from_signal(event, ledger, action=SignalAction.ADD, now=now)
    if operation == "PARTIAL_FROM_SIGNAL":
        return _runner_from_signal(event, ledger, action=SignalAction.PARTIAL, now=now)
    if operation == "CLOSE_FROM_SIGNAL":
        return _close_from_signal(event, ledger, now=now)
    if operation == "GET_OPEN":
        return _get_open(event, ledger)
    raise PaperRuntimeError("UNSUPPORTED_PAPER_OPERATION")


def _open_from_decision(event: Mapping[str, Any], ledger: Any) -> dict[str, Any]:
    engine = _mapping(event, "engine_result")
    if engine.get("ok") is not True:
        raise PaperRuntimeError("ENGINE_DECISION_NOT_OK")
    if str(engine.get("mode", "")).upper() != "PAPER":
        raise PaperRuntimeError("ENGINE_MODE_NOT_PAPER")
    if engine.get("live_trading_enabled") is not False:
        raise PaperRuntimeError("LIVE_TRADING_FLAG_NOT_DISABLED")

    risk = _mapping(engine, "risk")
    if str(risk.get("status", "")).upper() != "APPROVED":
        raise PaperRuntimeError("RISK_DECISION_NOT_APPROVED")

    signal = _engine_signal(_mapping(engine, "signal"))
    if signal.action != SignalAction.ENTRY_LONG:
        raise PaperRuntimeError("OPEN_REQUIRES_ENTRY_LONG")
    decision = _engine_decision(_mapping(engine, "decision"), signal.symbol)
    if decision.status != DecisionStatus.SELECTED:
        raise PaperRuntimeError("INSTRUMENT_DECISION_NOT_SELECTED")
    if decision.instrument_selected == InstrumentSelected.NONE:
        raise PaperRuntimeError("NO_INSTRUMENT_SELECTED")

    existing = ledger.find_open(signal.symbol, decision.instrument_selected)
    if existing:
        if existing[0].signal_id == signal.signal_id:
            return _trade_result(
                "OPEN_FROM_DECISION",
                "ALREADY_OPEN",
                existing[0],
                ledger,
                idempotent=True,
            )
        raise PaperRuntimeError("OPEN_POSITION_ALREADY_EXISTS")

    nav = _positive_float(risk.get("nav"), "risk.nav")
    sizing = event.get("sizing", {})
    sizing_payload = _as_mapping(sizing, "sizing")
    limits = PortfolioLimits(
        nav=nav,
        risk_per_trade_pct=_positive_float(
            sizing_payload.get("risk_per_trade_pct", 0.005),
            "risk_per_trade_pct",
        ),
        max_capital_per_trade_pct=_positive_float(
            sizing_payload.get("max_capital_per_trade_pct", 0.02),
            "max_capital_per_trade_pct",
        ),
    )
    pricing_payload = _as_mapping(event.get("pricing", {}), "pricing")
    pricing, pricing_source = _entry_pricing(decision, pricing_payload)
    risk_snapshot = _as_mapping(risk.get("risk_snapshot", {}), "risk.risk_snapshot")
    proposed = _as_mapping(risk_snapshot.get("proposed", {}), "risk.proposed")
    sector = resolve_sector(signal.symbol, str(proposed.get("sector", "")))
    if not is_verified_sector(sector):
        raise PaperRuntimeError("SECTOR_DATA_UNVERIFIED")

    trade = PaperTradingPipeline(ledger, limits).process_entry(
        signal=signal,
        decision=decision,
        pricing=pricing,
        sector=sector,
    )
    result = _trade_result(
        "OPEN_FROM_DECISION",
        "OPENED",
        trade,
        ledger,
        idempotent=False,
    )
    result["pricing_source"] = pricing_source
    result["risk_policy_version"] = str(risk.get("policy_version", ""))
    return result


def _runner_from_signal(
    event: Mapping[str, Any],
    ledger: Any,
    *,
    action: SignalAction,
    now: datetime | None,
) -> dict[str, Any]:
    received_at = now or datetime.now(UTC)
    signal = parse_pine_signal(
        dict(_mapping(event, "signal")),
        received_at=received_at,
        max_age_minutes=_positive_int(
            event.get("signal_max_age_minutes", 30),
            "signal_max_age_minutes",
        ),
    )
    if signal.action != action:
        required = "ADD" if action == SignalAction.ADD else "PARTIAL"
        raise PaperRuntimeError(f"RUNNER_OPERATION_REQUIRES_{required}_SIGNAL")

    open_before = ledger.find_open(signal.symbol)
    if not open_before:
        return {
            "operation": f"{action.value}_FROM_SIGNAL",
            "status": "NO_OPEN_POSITION",
            "symbol": signal.symbol,
            "updated_trades": [],
            "paper_ledger_updated": False,
            "live_trading_enabled": False,
            "account_id": getattr(ledger, "account_id", None),
        }

    pricing = _as_mapping(event.get("pricing", {}), "pricing")
    option_fill = _optional_nonnegative_float(
        pricing.get("option_fill_price"), "option_fill_price"
    )
    stock_fill = _optional_nonnegative_float(
        pricing.get("stock_fill_price"), "stock_fill_price"
    )
    pipeline = PaperTradingPipeline(ledger, PortfolioLimits(nav=1.0))
    if action == SignalAction.ADD:
        updated = pipeline.process_add(
            signal=signal,
            option_fill_price=option_fill,
            stock_fill_price=stock_fill,
            fill_time=received_at,
        )
        status = "ADDED"
        operation = "ADD_FROM_SIGNAL"
    else:
        updated = pipeline.process_partial(
            signal=signal,
            option_fill_price=option_fill,
            stock_fill_price=stock_fill,
            fill_time=received_at,
        )
        status = "PARTIAL"
        operation = "PARTIAL_FROM_SIGNAL"

    return {
        "operation": operation,
        "status": status,
        "symbol": signal.symbol,
        "runner_stage": signal.runner_stage,
        "position_fraction": signal.position_fraction,
        "updated_trades": [trade.to_dict() for trade in updated],
        "paper_ledger_updated": bool(updated),
        "live_trading_enabled": False,
        "account_id": getattr(ledger, "account_id", None),
    }


def _close_from_signal(
    event: Mapping[str, Any],
    ledger: Any,
    *,
    now: datetime | None,
) -> dict[str, Any]:
    signal_payload = _mapping(event, "signal")
    received_at = now or datetime.now(UTC)
    signal = parse_pine_signal(
        dict(signal_payload),
        received_at=received_at,
        max_age_minutes=_positive_int(
            event.get("signal_max_age_minutes", 30),
            "signal_max_age_minutes",
        ),
    )
    if signal.action != SignalAction.EXIT:
        raise PaperRuntimeError("CLOSE_REQUIRES_EXIT_SIGNAL")

    pricing = _as_mapping(event.get("pricing", {}), "pricing")
    option_exit = _optional_nonnegative_float(
        pricing.get("option_exit_price"), "option_exit_price"
    )
    stock_exit = _optional_nonnegative_float(
        pricing.get("stock_exit_price"), "stock_exit_price"
    )
    open_before = ledger.find_open(signal.symbol)
    if not open_before:
        return {
            "operation": "CLOSE_FROM_SIGNAL",
            "status": "NO_OPEN_POSITION",
            "symbol": signal.symbol,
            "closed_trades": [],
            "paper_ledger_updated": False,
            "live_trading_enabled": False,
            "account_id": getattr(ledger, "account_id", None),
        }

    closed = PaperTradingPipeline(ledger, PortfolioLimits(nav=1.0)).process_exit(
        signal=signal,
        option_exit_price=option_exit,
        stock_exit_price=stock_exit,
        exit_time=received_at,
    )
    return {
        "operation": "CLOSE_FROM_SIGNAL",
        "status": "CLOSED",
        "symbol": signal.symbol,
        "closed_trades": [trade.to_dict() for trade in closed],
        "paper_ledger_updated": True,
        "live_trading_enabled": False,
        "account_id": getattr(ledger, "account_id", None),
    }


def _get_open(event: Mapping[str, Any], ledger: Any) -> dict[str, Any]:
    symbol = _required_text(event.get("symbol"), "symbol").upper()
    selected = event.get("instrument")
    instrument = None
    if selected not in (None, ""):
        try:
            instrument = InstrumentSelected(str(selected).upper())
        except ValueError as exc:
            raise PaperRuntimeError("INVALID_INSTRUMENT_FILTER") from exc
        if instrument == InstrumentSelected.NONE:
            raise PaperRuntimeError("INVALID_INSTRUMENT_FILTER")
    trades = ledger.find_open(symbol, instrument)
    return {
        "operation": "GET_OPEN",
        "status": "OPEN_POSITIONS" if trades else "NO_OPEN_POSITION",
        "symbol": symbol,
        "count": len(trades),
        "trades": [trade.to_dict() for trade in trades],
        "live_trading_enabled": False,
        "account_id": getattr(ledger, "account_id", None),
    }


def _engine_signal(payload: Mapping[str, Any]):
    received = _timestamp(payload.get("received_at"), "signal.received_at")
    signal_payload = {
        "signal_id": payload.get("signal_id"),
        "symbol": payload.get("symbol"),
        "action": payload.get("action"),
        "strategy": payload.get("strategy"),
        "strategy_version": payload.get("strategy_version"),
        "timeframe": payload.get("timeframe"),
        "price": payload.get("price"),
        "bar_time": payload.get("bar_time"),
    }
    return parse_pine_signal(signal_payload, received_at=received, max_age_minutes=30)


def _engine_decision(payload: Mapping[str, Any], symbol: str) -> Decision:
    try:
        status = DecisionStatus(str(payload.get("status", "")).upper())
        instrument = InstrumentSelected(
            str(payload.get("instrument_selected", "")).upper()
        )
    except ValueError as exc:
        raise PaperRuntimeError("INVALID_ENGINE_DECISION") from exc

    contract_payload = payload.get("selected_contract")
    contract = None
    if contract_payload is not None:
        values = _as_mapping(contract_payload, "selected_contract")
        contract = OptionCandidate(
            symbol=symbol,
            expiration=_required_text(values.get("expiration"), "expiration"),
            strike=_positive_float(values.get("strike"), "strike"),
            option_type=_required_text(values.get("option_type"), "option_type").upper(),
            dte=_nonnegative_int(values.get("dte"), "dte"),
            bid=_nonnegative_float(values.get("bid"), "bid"),
            ask=_positive_float(values.get("ask"), "ask"),
            open_interest=_nonnegative_int(
                values.get("open_interest", 0), "open_interest"
            ),
            volume=_nonnegative_int(values.get("volume", 0), "volume"),
            delta=(
                None
                if values.get("delta") in (None, "")
                else float(values.get("delta"))
            ),
        )
    return Decision(
        symbol=symbol,
        status=status,
        instrument_selected=instrument,
        fallback_reason=str(payload.get("fallback_reason", "")),
        selected_contract=contract,
        created_at=str(payload.get("created_at", "")),
    )


def _entry_pricing(
    decision: Decision, payload: Mapping[str, Any]
) -> tuple[EntryPricing, str]:
    if decision.instrument_selected == InstrumentSelected.OPTION:
        if decision.selected_contract is None:
            raise PaperRuntimeError("OPTION_CONTRACT_REQUIRED")
        explicit = payload.get("option_premium")
        if explicit not in (None, ""):
            return (
                EntryPricing(option_premium=_positive_float(explicit, "option_premium")),
                "EXPLICIT_OPTION_PAPER_FILL",
            )
        return (
            EntryPricing(option_premium=decision.selected_contract.ask),
            "SELECTED_OPTION_ASK",
        )

    if decision.instrument_selected == InstrumentSelected.STOCK:
        return (
            EntryPricing(
                stock_price=_positive_float(payload.get("stock_price"), "stock_price"),
                stock_stop_price=_positive_float(
                    payload.get("stock_stop_price"), "stock_stop_price"
                ),
            ),
            "EXPLICIT_STOCK_PAPER_FILL_AND_STOP",
        )
    raise PaperRuntimeError("NO_INSTRUMENT_SELECTED")


def _trade_result(
    operation: str,
    status: str,
    trade: Any,
    ledger: Any,
    *,
    idempotent: bool,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "status": status,
        "trade": trade.to_dict(),
        "paper_trade_written": not idempotent,
        "paper_ledger_updated": not idempotent,
        "idempotent": idempotent,
        "live_trading_enabled": False,
        "account_id": getattr(ledger, "account_id", None),
    }


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in payload:
        raise PaperRuntimeError(f"{key.upper()}_REQUIRED")
    return _as_mapping(payload[key], key)


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PaperRuntimeError(f"{name} must be an object")
    return value


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PaperRuntimeError(f"{name} is required")
    return text


def _timestamp(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_required_text(value, name))
    except ValueError as exc:
        raise PaperRuntimeError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PaperRuntimeError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _positive_float(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise PaperRuntimeError(f"{name} must be positive")
    return number


def _nonnegative_float(value: Any, name: str) -> float:
    number = _number(value, name)
    if number < 0:
        raise PaperRuntimeError(f"{name} must be non-negative")
    return number


def _optional_nonnegative_float(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    return _nonnegative_float(value, name)


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PaperRuntimeError(f"{name} must be numeric") from exc


def _positive_int(value: Any, name: str) -> int:
    number = _nonnegative_int(value, name)
    if number <= 0:
        raise PaperRuntimeError(f"{name} must be positive")
    return number


def _nonnegative_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PaperRuntimeError(f"{name} must be an integer") from exc
    if number < 0:
        raise PaperRuntimeError(f"{name} must be non-negative")
    return number
