"""Fail-closed staging runtime for real Daily Alpha entry decisions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .fallback import InstrumentFallbackEngine
from .models import OptionCandidate, StockCandidate
from .portfolio import (
    AssetType,
    Greeks,
    PortfolioDataStatus,
    PortfolioSnapshot,
    Position,
)
from .risk import (
    PortfolioRiskEngine,
    PortfolioRiskState,
    ProposedTradeRisk,
)
from .signals import SignalAction, parse_pine_signal


class RuntimeInputError(ValueError):
    """A staging runtime event is incomplete or unsafe to evaluate."""


def evaluate_entry_event(
    event: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Run signal -> portfolio risk -> OPTION/STOCK fallback for one entry.

    ORATS credentials never cross this boundary. The caller supplies normalized
    option data plus its observation time. Stale or unavailable option data
    remains a DATA_ERROR and can never authorize a stock fallback.
    """
    received_at = _aware(now or datetime.now(UTC))
    signal_payload = _mapping(event, "signal")
    signal = parse_pine_signal(
        dict(signal_payload),
        received_at=received_at,
        max_age_minutes=_positive_int(event.get("signal_max_age_minutes", 30), "signal_max_age_minutes"),
    )
    if signal.action != SignalAction.ENTRY_LONG:
        raise RuntimeInputError("EVALUATE_ENTRY_REQUIRES_ENTRY_LONG")

    snapshot = _portfolio_snapshot(_mapping(event, "portfolio"))
    risk_state = _risk_state(event.get("risk_state", {}))
    proposed = _proposed_trade(_mapping(event, "proposed_trade"), signal.symbol, signal.signal_id)
    risk = PortfolioRiskEngine().evaluate(
        snapshot=snapshot,
        state=risk_state,
        proposed=proposed,
    )

    if not risk.approved:
        decision = InstrumentFallbackEngine().select(
            symbol=signal.symbol,
            signal_active=True,
            risk_gate_passed=False,
            option_data_fresh=True,
            option_data_available=True,
            options=(),
            stock=None,
        )
        return _result(signal, risk, decision, option_data_checked=False)

    market = _mapping(event, "market")
    option_data_available = bool(market.get("option_data_available", False))
    option_data_fresh = _option_data_is_fresh(
        market,
        reference=received_at,
        available=option_data_available,
    )
    options = _options(market.get("options", ()), signal.symbol)
    stock = _stock(market.get("stock"), signal.symbol)

    decision = InstrumentFallbackEngine().select(
        symbol=signal.symbol,
        signal_active=True,
        risk_gate_passed=True,
        option_data_fresh=option_data_fresh,
        option_data_available=option_data_available,
        options=options,
        stock=stock,
    )
    return _result(signal, risk, decision, option_data_checked=True)


def _result(signal: Any, risk: Any, decision: Any, *, option_data_checked: bool) -> dict[str, Any]:
    return {
        "signal": {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "action": signal.action.value,
            "strategy": signal.strategy,
            "strategy_version": signal.strategy_version,
            "timeframe": signal.timeframe,
            "price": signal.price,
            "bar_time": signal.bar_time.isoformat(),
            "received_at": signal.received_at.isoformat(),
        },
        "risk": risk.to_dict(),
        "decision": decision.to_dict(),
        "option_data_checked": option_data_checked,
        "paper_trade_written": False,
        "live_trading_enabled": False,
    }


def _portfolio_snapshot(payload: Mapping[str, Any]) -> PortfolioSnapshot:
    positions = tuple(_position(item) for item in _sequence(payload.get("positions", ()), "positions"))
    try:
        status = PortfolioDataStatus(str(payload.get("data_status", "AVAILABLE")).upper())
        return PortfolioSnapshot.create(
            snapshot_id=_required_text(payload.get("snapshot_id"), "snapshot_id"),
            account_id=_required_text(payload.get("account_id"), "account_id"),
            source=_required_text(payload.get("source"), "source"),
            as_of=_required_text(payload.get("as_of"), "as_of"),
            cash=_number(payload.get("cash"), "cash"),
            buying_power=_number(payload.get("buying_power"), "buying_power"),
            positions=positions,
            data_status=status,
            reconciliation_errors=tuple(
                str(item) for item in _sequence(payload.get("reconciliation_errors", ()), "reconciliation_errors")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"INVALID_PORTFOLIO:{type(exc).__name__}") from exc


def _position(payload: Any) -> Position:
    values = _as_mapping(payload, "position")
    try:
        asset_type = AssetType(str(values.get("asset_type", "")).upper())
        greeks_payload = values.get("greeks")
        greeks = None
        if greeks_payload is not None:
            parsed = _as_mapping(greeks_payload, "greeks")
            greeks = Greeks(
                delta=_number(parsed.get("delta", 0.0), "delta"),
                gamma=_number(parsed.get("gamma", 0.0), "gamma"),
                theta=_number(parsed.get("theta", 0.0), "theta"),
                vega=_number(parsed.get("vega", 0.0), "vega"),
            )
        return Position(
            symbol=_required_text(values.get("symbol"), "position.symbol").upper(),
            asset_type=asset_type,
            quantity=_number(values.get("quantity"), "quantity"),
            mark=_number(values.get("mark"), "mark"),
            cost_basis=_number(values.get("cost_basis"), "cost_basis"),
            multiplier=_positive_int(values.get("multiplier", 1), "multiplier"),
            sector=str(values.get("sector", "UNKNOWN")),
            expiration=str(values["expiration"]) if values.get("expiration") else None,
            greeks=greeks,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"INVALID_POSITION:{type(exc).__name__}") from exc


def _risk_state(value: Any) -> PortfolioRiskState:
    payload = _as_mapping(value, "risk_state")
    try:
        return PortfolioRiskState(
            daily_new_risk=_number(payload.get("daily_new_risk", 0.0), "daily_new_risk"),
            new_positions_today=_nonnegative_int(payload.get("new_positions_today", 0), "new_positions_today"),
            daily_loss=_number(payload.get("daily_loss", 0.0), "daily_loss"),
            weekly_drawdown=_number(payload.get("weekly_drawdown", 0.0), "weekly_drawdown"),
            rolling_drawdown=_number(payload.get("rolling_drawdown", 0.0), "rolling_drawdown"),
            total_risk=_number(payload.get("total_risk", 0.0), "total_risk"),
            beta_exposure=_number(payload.get("beta_exposure", 0.0), "beta_exposure"),
            delta_exposure=_number(payload.get("delta_exposure", 0.0), "delta_exposure"),
            cluster_risk=_named_risk(payload.get("cluster_risk", ()), "cluster_risk"),
            sector_risk=_named_risk(payload.get("sector_risk", ()), "sector_risk"),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"INVALID_RISK_STATE:{type(exc).__name__}") from exc


def _proposed_trade(payload: Mapping[str, Any], symbol: str, signal_id: str) -> ProposedTradeRisk:
    try:
        return ProposedTradeRisk(
            decision_id=str(payload.get("decision_id") or signal_id),
            symbol=symbol,
            planned_loss=_number(payload.get("planned_loss"), "planned_loss"),
            cluster_id=str(payload.get("cluster_id") or symbol),
            sector=str(payload.get("sector", "UNKNOWN")),
            beta_exposure=_number(payload.get("beta_exposure", 0.0), "beta_exposure"),
            delta_exposure=_number(payload.get("delta_exposure", 0.0), "delta_exposure"),
            event_risk=bool(payload.get("event_risk", False)),
            liquidity_score=_number(payload.get("liquidity_score", 1.0), "liquidity_score"),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"INVALID_PROPOSED_TRADE:{type(exc).__name__}") from exc


def _option_data_is_fresh(
    market: Mapping[str, Any], *, reference: datetime, available: bool
) -> bool:
    if not available:
        return False
    observed = market.get("option_data_observed_at")
    if not observed:
        return False
    try:
        timestamp = _aware(datetime.fromisoformat(str(observed).replace("Z", "+00:00")))
    except ValueError:
        return False
    mode = str(market.get("orats_mode", "delayed")).lower()
    if mode not in {"delayed", "live"}:
        return False
    max_age = 25 if mode == "delayed" else 5
    age_minutes = (reference - timestamp).total_seconds() / 60
    return -1 <= age_minutes <= max_age


def _options(value: Any, symbol: str) -> tuple[OptionCandidate, ...]:
    items = _sequence(value, "options")
    candidates: list[OptionCandidate] = []
    for item in items:
        payload = _as_mapping(item, "option")
        try:
            candidate = OptionCandidate(
                symbol=symbol,
                expiration=_required_text(payload.get("expiration"), "expiration"),
                strike=_number(payload.get("strike"), "strike"),
                option_type=_required_text(payload.get("option_type"), "option_type").upper(),
                dte=_nonnegative_int(payload.get("dte"), "dte"),
                bid=_number(payload.get("bid"), "bid"),
                ask=_number(payload.get("ask"), "ask"),
                open_interest=_nonnegative_int(payload.get("open_interest", 0), "open_interest"),
                volume=_nonnegative_int(payload.get("volume", 0), "volume"),
                delta=(
                    None
                    if payload.get("delta") in (None, "")
                    else _number(payload.get("delta"), "delta")
                ),
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeInputError(f"INVALID_OPTION:{type(exc).__name__}") from exc
        candidates.append(candidate)
    return tuple(candidates)


def _stock(value: Any, symbol: str) -> StockCandidate | None:
    if value is None:
        return None
    payload = _as_mapping(value, "stock")
    try:
        return StockCandidate(
            symbol=symbol,
            price=_number(payload.get("price"), "stock.price"),
            average_daily_dollar_volume=_number(
                payload.get("average_daily_dollar_volume"),
                "average_daily_dollar_volume",
            ),
            eligible=bool(payload.get("eligible", True)),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"INVALID_STOCK:{type(exc).__name__}") from exc


def _named_risk(value: Any, name: str) -> tuple[tuple[str, float], ...]:
    if isinstance(value, Mapping):
        return tuple((str(key), _number(amount, name)) for key, amount in value.items())
    pairs = []
    for item in _sequence(value, name):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise RuntimeInputError(f"{name} entries must be [name, amount]")
        pairs.append((str(item[0]), _number(item[1], name)))
    return tuple(pairs)


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in payload:
        raise RuntimeInputError(f"{key.upper()}_REQUIRED")
    return _as_mapping(payload[key], key)


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeInputError(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise RuntimeInputError(f"{name} must be an array")
    return tuple(value)


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RuntimeInputError(f"{name} is required")
    return text


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"{name} must be numeric") from exc


def _positive_int(value: Any, name: str) -> int:
    number = _nonnegative_int(value, name)
    if number <= 0:
        raise RuntimeInputError(f"{name} must be positive")
    return number


def _nonnegative_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError(f"{name} must be an integer") from exc
    if number < 0:
        raise RuntimeInputError(f"{name} must be non-negative")
    return number


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
