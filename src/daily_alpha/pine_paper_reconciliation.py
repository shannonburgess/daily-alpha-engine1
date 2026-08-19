"""Reconcile Pine signal state before paper-only execution.

This wrapper preserves valid signals that arrive outside the regular execution
window and makes TradingView/paper-ledger state disagreements explicit. It never
authorizes live trading and delegates all actual paper fills to the existing
AwsPinePaperExecutor after the reconciliation gates pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .lifecycle_sizing import resolve_lifecycle_sizing
from .orats import OratsError
from .pine_paper_orchestrator import (
    AwsPinePaperExecutor,
    PinePaperExecutionError,
    _aware,
    _regular_execution_window,
    _required_text,
)
from .sectors import is_verified_sector, resolve_sector

MAX_ARMED_AGE_DAYS = 7


@dataclass(frozen=True)
class ArmedReplayDecision:
    """Pure revalidation result before any paper-ledger mutation."""

    status: str
    reason: str
    ingress: dict[str, Any] | None

    @property
    def should_execute(self) -> bool:
        return self.status == "EXECUTE_REVALIDATED_ARMED_SIGNAL" and self.ingress is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReconciledAwsPinePaperExecutor(AwsPinePaperExecutor):
    """Add durable signal-state semantics ahead of the existing paper executor."""

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

        # Runner-management events are meaningful only when the paper ledger has
        # the corresponding position. A TradingView strategy can carry a
        # historically simulated position that the realtime paper ledger never
        # opened, so never manufacture an ADD/PARTIAL/EXIT in that condition.
        if action in {"ADD", "PARTIAL", "EXIT"}:
            open_trades = self.ledger.find_open(symbol)
            if not open_trades:
                return _result(
                    disposition="STATE_MISMATCH",
                    reason="TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER",
                    action=action,
                    symbol=symbol,
                    context={
                        "state_mismatch": True,
                        "orphan_action": action,
                        "signal_id": str(ingress.get("signal_id", "")),
                        "runner_stage": ingress.get("runner_stage"),
                        "replay_allowed": False,
                    },
                )

        # Preserve an otherwise eligible entry outside market hours rather than
        # silently converting it to NO_TRADE. Safety/eligibility gates are checked
        # before arming; all market data, risk, no-chase and instrument context must
        # be refreshed again before a later fill.
        if action == "ENTRY_LONG" and not _regular_execution_window(timestamp):
            lifecycle = resolve_lifecycle_sizing(ingress.get("lifecycle"))
            if lifecycle is not None and not lifecycle.entry_allowed:
                return _result(
                    disposition="NO_TRADE",
                    reason="LIFECYCLE_EXTENDED_NO_CHASE",
                    action=action,
                    symbol=symbol,
                )
            sector = resolve_sector(symbol, str(ingress.get("sector", "")))
            if not is_verified_sector(sector):
                return _result(
                    disposition="NO_TRADE",
                    reason="SECTOR_DATA_UNVERIFIED",
                    action=action,
                    symbol=symbol,
                )
            return _result(
                disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                reason="MARKET_CLOSED_REVALIDATION_REQUIRED",
                action=action,
                symbol=symbol,
                context={
                    "armed": True,
                    "armed_at": timestamp.isoformat(),
                    "signal_id": str(ingress.get("signal_id", "")),
                    "revalidation_required": True,
                    "refresh_orats": True,
                    "refresh_portfolio_risk": True,
                    "refresh_no_chase": True,
                },
            )

        if action in {"ADD", "PARTIAL", "EXIT"} and not _regular_execution_window(
            timestamp
        ):
            return _result(
                disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                reason="MARKET_CLOSED_RUNNER_REVALIDATION_REQUIRED",
                action=action,
                symbol=symbol,
                context={
                    "armed": True,
                    "armed_at": timestamp.isoformat(),
                    "signal_id": str(ingress.get("signal_id", "")),
                    "runner_stage": ingress.get("runner_stage"),
                    "revalidation_required": True,
                    "refresh_instrument_quote": True,
                },
            )

        return super().execute(ingress, now=timestamp)

    def replay_armed(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Refresh price/context and replay one durably armed signal fail-closed."""
        timestamp = _aware(now or datetime.now(UTC))
        action = str(ingress.get("action", "")).upper()
        symbol = _required_text(ingress.get("symbol"), "symbol").upper()

        if not _regular_execution_window(timestamp):
            return _result(
                disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                reason="REPLAY_WAITING_FOR_REGULAR_WINDOW",
                action=action,
                symbol=symbol,
                context={"replay_attempted": False},
            )

        if action in {"ADD", "PARTIAL", "EXIT"} and not self.ledger.find_open(symbol):
            return _result(
                disposition="STATE_MISMATCH",
                reason="TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER",
                action=action,
                symbol=symbol,
                context={
                    "state_mismatch": True,
                    "orphan_action": action,
                    "signal_id": str(ingress.get("signal_id", "")),
                    "replay_allowed": False,
                },
            )

        try:
            chain = self._orats().fetch_chain(symbol, as_of=timestamp)
        except OratsError as exc:
            return _result(
                disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                reason="REPLAY_DATA_ERROR_RETRY_REQUIRED",
                action=action,
                symbol=symbol,
                context={
                    "replay_attempted": True,
                    "data_error": str(exc),
                    "retry_allowed": True,
                },
            )

        price = chain.stock_price
        if price is None or price <= 0:
            return _result(
                disposition="ARMED_FOR_NEXT_TRADABLE_WINDOW",
                reason="REPLAY_UNDERLYING_PRICE_UNAVAILABLE",
                action=action,
                symbol=symbol,
                context={"replay_attempted": True, "retry_allowed": True},
            )

        decision = prepare_armed_replay(
            ingress,
            market_price=float(price),
            now=timestamp,
        )
        if not decision.should_execute:
            disposition = (
                "ARMED_FOR_NEXT_TRADABLE_WINDOW"
                if decision.status == "WAIT_REVALIDATION"
                else decision.status
            )
            return _result(
                disposition=disposition,
                reason=decision.reason,
                action=action,
                symbol=symbol,
                context={
                    "replay_attempted": True,
                    "market_price": float(price),
                    "decision": decision.to_dict(),
                },
            )

        assert decision.ingress is not None
        result = super().execute(decision.ingress, now=timestamp)
        context = dict(result.get("context") or {})
        context.update(
            {
                "replayed_from_armed_signal": True,
                "origin_signal_id": str(ingress.get("signal_id", "")),
                "origin_signal_price": ingress.get("price"),
                "replay_market_price": float(price),
            }
        )
        result["context"] = context
        return result


def prepare_armed_replay(
    ingress: Mapping[str, Any],
    *,
    market_price: float,
    now: datetime,
) -> ArmedReplayDecision:
    """Create a fresh execution-time signal without silently weakening no-chase.

    ENTRY replay requires an explicit ``replay_max_price`` produced by the signal
    source. Legacy alerts without that execution ceiling remain armed and visible;
    they are never filled using a guessed chase threshold.
    """
    timestamp = _aware(now)
    if not _regular_execution_window(timestamp):
        return ArmedReplayDecision(
            "WAIT_REVALIDATION",
            "REPLAY_WAITING_FOR_REGULAR_WINDOW",
            None,
        )
    if market_price <= 0:
        raise PinePaperExecutionError("REPLAY_MARKET_PRICE_MUST_BE_POSITIVE")

    action = str(ingress.get("action", "")).upper()
    if action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
        raise PinePaperExecutionError("PINE_ACTION_UNSUPPORTED")

    origin_time = _origin_time(ingress)
    if timestamp - origin_time > timedelta(days=MAX_ARMED_AGE_DAYS):
        return ArmedReplayDecision(
            "CANCELLED_REPLAY",
            "REPLAY_SIGNAL_EXPIRED",
            None,
        )

    if action == "ENTRY_LONG":
        raw_ceiling = ingress.get("replay_max_price")
        if raw_ceiling in (None, ""):
            return ArmedReplayDecision(
                "WAIT_REVALIDATION",
                "REPLAY_NO_CHASE_CEILING_REQUIRED",
                None,
            )
        try:
            ceiling = float(raw_ceiling)
        except (TypeError, ValueError) as exc:
            raise PinePaperExecutionError("REPLAY_MAX_PRICE_INVALID") from exc
        if ceiling <= 0:
            raise PinePaperExecutionError("REPLAY_MAX_PRICE_INVALID")

        raw_stop = ingress.get("stock_stop_price")
        if raw_stop not in (None, ""):
            try:
                stop = float(raw_stop)
            except (TypeError, ValueError) as exc:
                raise PinePaperExecutionError("REPLAY_STOP_PRICE_INVALID") from exc
            if stop <= 0:
                raise PinePaperExecutionError("REPLAY_STOP_PRICE_INVALID")
            if market_price <= stop:
                return ArmedReplayDecision(
                    "CANCELLED_REPLAY",
                    "REPLAY_ENTRY_BELOW_OR_AT_STOP",
                    None,
                )
        if market_price > ceiling:
            return ArmedReplayDecision(
                "CANCELLED_REPLAY",
                "REPLAY_ENTRY_CHASE_LIMIT_EXCEEDED",
                None,
            )

    origin_signal_id = str(ingress.get("signal_id", "")).strip()
    fresh = dict(ingress)
    fresh.update(
        {
            "signal_id": (
                f"{origin_signal_id}-REPLAY-"
                f"{timestamp.strftime('%Y%m%dT%H%M%S')}"
            ),
            "price": float(market_price),
            "bar_time": timestamp.isoformat(),
            "received_at": timestamp.isoformat(),
            "origin_signal_id": origin_signal_id,
            "origin_signal_price": ingress.get("price"),
            "origin_signal_bar_time": ingress.get("bar_time"),
            "execution_timing": "ARMED_REPLAY_REGULAR_SESSION",
        }
    )
    return ArmedReplayDecision(
        "EXECUTE_REVALIDATED_ARMED_SIGNAL",
        "ARMED_SIGNAL_REVALIDATED",
        fresh,
    )


def _origin_time(ingress: Mapping[str, Any]) -> datetime:
    raw = ingress.get("received_at") or ingress.get("bar_time")
    if not raw:
        raise PinePaperExecutionError("ARMED_SIGNAL_ORIGIN_TIME_REQUIRED")
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise PinePaperExecutionError("ARMED_SIGNAL_ORIGIN_TIME_INVALID") from exc
    return _aware(parsed)


def _result(
    *,
    disposition: str,
    reason: str,
    action: str,
    symbol: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "reason": reason,
        "action": action,
        "symbol": symbol,
        "paper_execution_triggered": False,
        "paper_ledger_updated": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
        "paper": {},
        "context": dict(context or {}),
    }
