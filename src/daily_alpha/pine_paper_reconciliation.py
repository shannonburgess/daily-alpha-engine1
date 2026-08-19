"""Reconcile Pine signal state before paper-only execution.

This wrapper preserves valid signals that arrive outside the regular execution
window and makes TradingView/paper-ledger state disagreements explicit. It never
authorizes live trading and delegates all actual paper fills to the existing
AwsPinePaperExecutor after the reconciliation gates pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .lifecycle_sizing import resolve_lifecycle_sizing
from .pine_paper_orchestrator import (
    AwsPinePaperExecutor,
    PinePaperExecutionError,
    _aware,
    _regular_execution_window,
    _required_text,
)
from .sectors import is_verified_sector, resolve_sector


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
