"""Point-in-time observation adapters for research-only strategy forensics.

This module converts immutable Daily Alpha decisions plus subsequently observed
price bars into the fixed path consumed by ``strategy_forensics``. Evaluation
cutoffs are explicit so later bars cannot silently leak into an earlier forensic
horizon. Pine outcome mapping is deliberately fail-closed when a trustworthy
underlying stop, execution-time price, or timestamp is unavailable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .strategy_forensics import OpportunityPath


@dataclass(frozen=True)
class DecisionObservation:
    decision_id: str
    symbol: str
    strategy_version: str
    decision: str
    reason: str
    observed_at: datetime
    reference_price: float
    stop_price: float
    executed: bool = False
    exit_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        return payload


@dataclass(frozen=True)
class PriceBarObservation:
    observed_at: datetime
    high: float
    low: float
    close: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        return payload


@dataclass(frozen=True)
class ForensicsPathEvidence:
    decision_id: str
    decision_observed_at: str
    evaluation_cutoff: str
    first_bar_at: str
    last_bar_at: str
    bars_used: int
    ignored_predecision_bars: int
    ignored_after_cutoff_bars: int
    path: OpportunityPath
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def decision_observation_from_pine_outcome(
    ingress: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> DecisionObservation:
    """Map one canonical Pine ENTRY outcome into underlying-price forensics.

    The diagnostic studies the underlying signal path rather than option P/L. It
    therefore requires the strategy's explicit ``stock_stop_price``. Replayed
    outcomes must expose an execution-time underlying price and a trustworthy
    execution timestamp; the caller may supply ``observed_at`` only for legacy
    outcomes that predate persisted evaluation timestamps.
    """
    if not isinstance(ingress, Mapping) or not isinstance(execution, Mapping):
        raise TypeError("FORENSICS_PINE_OUTCOME_MUST_BE_OBJECT")
    action = _required_text(
        ingress.get("action"), "FORENSICS_PINE_ACTION_REQUIRED"
    ).upper()
    if action != "ENTRY_LONG":
        raise ValueError("FORENSICS_PINE_ENTRY_REQUIRED")

    decision_id = _required_text(
        ingress.get("signal_id"), "FORENSICS_PINE_SIGNAL_ID_REQUIRED"
    )
    symbol = _required_text(
        ingress.get("symbol"), "FORENSICS_PINE_SYMBOL_REQUIRED"
    ).upper()
    strategy_version = _required_text(
        ingress.get("strategy_version"), "FORENSICS_PINE_STRATEGY_VERSION_REQUIRED"
    )
    stop_price = _positive_float(
        ingress.get("stock_stop_price"), "FORENSICS_PINE_STOP_PRICE_REQUIRED"
    )

    disposition = _required_text(
        execution.get("disposition"), "FORENSICS_PINE_DISPOSITION_REQUIRED"
    ).upper()
    reason = _required_text(execution.get("reason"), "FORENSICS_PINE_REASON_REQUIRED")
    context = execution.get("context")
    if not isinstance(context, Mapping):
        context = {}

    replay_attempted = bool(context.get("replay_attempted")) or bool(
        context.get("replayed_from_armed_signal")
    )
    replay_price = _optional_positive_float(context.get("replay_market_price"))
    if replay_price is None and replay_attempted:
        replay_price = _optional_positive_float(context.get("market_price"))
    reference_price = replay_price or _positive_float(
        ingress.get("price"), "FORENSICS_PINE_REFERENCE_PRICE_REQUIRED"
    )
    if stop_price >= reference_price:
        raise ValueError("FORENSICS_PINE_STOP_MUST_BE_BELOW_REFERENCE")

    event_time = observed_at or _execution_observed_at(
        ingress=ingress,
        execution=execution,
        context=context,
        replay_attempted=replay_attempted,
    )
    _require_aware(event_time, "FORENSICS_PINE_TIME_MUST_BE_TIMEZONE_AWARE")

    if disposition == "EXECUTED_PAPER":
        decision = "ENTRY"
        executed = True
    elif disposition in {
        "ARMED_FOR_NEXT_TRADABLE_WINDOW",
        "NO_TRADE",
        "CANCELLED_REPLAY",
        "DATA_ERROR",
    }:
        decision = "WAIT"
        executed = False
    else:
        raise ValueError("FORENSICS_PINE_DISPOSITION_UNSUPPORTED")

    return DecisionObservation(
        decision_id=decision_id,
        symbol=symbol,
        strategy_version=strategy_version,
        decision=decision,
        reason=reason,
        observed_at=event_time,
        reference_price=reference_price,
        stop_price=stop_price,
        executed=executed,
    )


def build_forensics_path(
    decision: DecisionObservation,
    bars: Iterable[PriceBarObservation],
    *,
    evaluation_cutoff: datetime,
    max_bars: int | None = None,
) -> ForensicsPathEvidence:
    """Build an auditable post-decision path bounded by an explicit cutoff."""
    _validate_decision(decision)
    _require_aware(evaluation_cutoff, "FORENSICS_CUTOFF_MUST_BE_TIMEZONE_AWARE")
    if evaluation_cutoff <= decision.observed_at:
        raise ValueError("FORENSICS_CUTOFF_MUST_FOLLOW_DECISION")
    if max_bars is not None and max_bars <= 0:
        raise ValueError("FORENSICS_MAX_BARS_MUST_BE_POSITIVE")

    observed = list(bars)
    for bar in observed:
        _validate_bar(bar)

    ignored_predecision = sum(bar.observed_at <= decision.observed_at for bar in observed)
    ignored_after_cutoff = sum(bar.observed_at > evaluation_cutoff for bar in observed)
    eligible = sorted(
        (
            bar
            for bar in observed
            if decision.observed_at < bar.observed_at <= evaluation_cutoff
        ),
        key=lambda bar: bar.observed_at,
    )
    if max_bars is not None:
        eligible = eligible[:max_bars]
    if not eligible:
        raise ValueError("FORENSICS_NO_POST_DECISION_BARS_IN_CUTOFF")

    timestamps = [bar.observed_at for bar in eligible]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("FORENSICS_DUPLICATE_BAR_TIMESTAMP")

    path = OpportunityPath(
        symbol=decision.symbol,
        strategy_version=decision.strategy_version,
        decision=decision.decision,
        reason=decision.reason,
        reference_price=decision.reference_price,
        stop_price=decision.stop_price,
        max_price_after=max(bar.high for bar in eligible),
        min_price_after=min(bar.low for bar in eligible),
        terminal_price=eligible[-1].close,
        bars_observed=len(eligible),
        executed=decision.executed,
        exit_price=decision.exit_price,
    )
    return ForensicsPathEvidence(
        decision_id=decision.decision_id,
        decision_observed_at=decision.observed_at.isoformat(),
        evaluation_cutoff=evaluation_cutoff.isoformat(),
        first_bar_at=eligible[0].observed_at.isoformat(),
        last_bar_at=eligible[-1].observed_at.isoformat(),
        bars_used=len(eligible),
        ignored_predecision_bars=ignored_predecision,
        ignored_after_cutoff_bars=ignored_after_cutoff,
        path=path,
    )


def _execution_observed_at(
    *,
    ingress: Mapping[str, Any],
    execution: Mapping[str, Any],
    context: Mapping[str, Any],
    replay_attempted: bool,
) -> datetime:
    receipt = execution.get("execution_receipt")
    if isinstance(receipt, Mapping) and receipt.get("occurred_at"):
        return _timestamp(receipt.get("occurred_at"), "FORENSICS_PINE_RECEIPT_TIME_INVALID")
    evaluated_at = execution.get("evaluated_at")
    if evaluated_at:
        return _timestamp(evaluated_at, "FORENSICS_PINE_EVALUATED_TIME_INVALID")
    armed_at = context.get("armed_at")
    if armed_at:
        return _timestamp(armed_at, "FORENSICS_PINE_ARMED_TIME_INVALID")
    if replay_attempted:
        raise ValueError("FORENSICS_PINE_REPLAY_OBSERVED_AT_REQUIRED")
    raw = ingress.get("received_at") or ingress.get("bar_time")
    return _timestamp(raw, "FORENSICS_PINE_TIME_REQUIRED")


def _validate_decision(decision: DecisionObservation) -> None:
    if not decision.decision_id.strip():
        raise ValueError("FORENSICS_DECISION_ID_REQUIRED")
    if not decision.symbol.strip() or not decision.strategy_version.strip():
        raise ValueError("FORENSICS_DECISION_IDENTITY_REQUIRED")
    if not decision.decision.strip():
        raise ValueError("FORENSICS_DECISION_REQUIRED")
    _require_aware(decision.observed_at, "FORENSICS_DECISION_TIME_MUST_BE_TIMEZONE_AWARE")
    if decision.reference_price <= 0 or decision.stop_price <= 0:
        raise ValueError("FORENSICS_DECISION_PRICES_MUST_BE_POSITIVE")
    if decision.stop_price >= decision.reference_price:
        raise ValueError("FORENSICS_DECISION_STOP_MUST_BE_BELOW_REFERENCE")
    if decision.executed and decision.exit_price is not None and decision.exit_price <= 0:
        raise ValueError("FORENSICS_DECISION_EXIT_PRICE_INVALID")
    if not decision.executed and decision.exit_price is not None:
        raise ValueError("FORENSICS_NONEXECUTED_EXIT_INVALID")


def _validate_bar(bar: PriceBarObservation) -> None:
    _require_aware(bar.observed_at, "FORENSICS_BAR_TIME_MUST_BE_TIMEZONE_AWARE")
    if bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
        raise ValueError("FORENSICS_BAR_PRICES_MUST_BE_POSITIVE")
    if bar.high < bar.low:
        raise ValueError("FORENSICS_BAR_RANGE_INVALID")
    if not bar.low <= bar.close <= bar.high:
        raise ValueError("FORENSICS_BAR_CLOSE_OUTSIDE_RANGE")


def _required_text(value: Any, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(message)
    return text


def _positive_float(value: Any, message: str) -> float:
    number = _optional_positive_float(value)
    if number is None:
        raise ValueError(message)
    return number


def _optional_positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _timestamp(value: Any, message: str) -> datetime:
    if value in (None, ""):
        raise ValueError(message)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(message) from exc
    _require_aware(parsed, message)
    return parsed


def _require_aware(value: datetime, message: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(message)
