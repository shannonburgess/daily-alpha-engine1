from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from .pine_parity_compare import ReferenceSignal

TRADINGVIEW_PINE_SOURCE = "TRADINGVIEW_PINE"
DA_TURTLE_STRATEGY = "DA_TURTLE_ADAPTIVE_TREND"
SUPPORTED_SIGNAL_ACTIONS = frozenset({"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"})


@dataclass(frozen=True, slots=True)
class PersistedReferenceSnapshot:
    """Complete, bounded TradingView strategy-event evidence for one isolated model book."""

    model_id: str
    strategy_version: str
    event_count_visible: int
    event_limit: int
    scan_items_evaluated: int
    signals: tuple[ReferenceSignal, ...]

    @property
    def complete(self) -> bool:
        return True


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _price(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("price must be numeric")
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("price must be numeric") from exc
    if not isfinite(price):
        raise ValueError("price must be finite")
    return price


def _optional_text(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def _reference_signal(
    event: Mapping[str, Any],
    *,
    expected_model_id: str,
    expected_strategy_version: str,
    expected_strategy: str,
    expected_source: str,
    expected_timeframe: str,
) -> ReferenceSignal:
    source = _required_text(event, "source")
    if source != expected_source:
        raise ValueError("persisted event source is not the frozen TradingView source")
    strategy = _required_text(event, "strategy")
    if strategy != expected_strategy:
        raise ValueError("persisted event strategy does not match the frozen strategy")
    model_id = _required_text(event, "model_id")
    if model_id != expected_model_id:
        raise ValueError("persisted event crossed the requested model book")
    strategy_version = _required_text(event, "strategy_version")
    if strategy_version != expected_strategy_version:
        raise ValueError("persisted event strategy_version does not match the requested model")
    timeframe = _required_text(event, "timeframe")
    if timeframe != expected_timeframe:
        raise ValueError("persisted event timeframe is not the frozen parity timeframe")

    action = _required_text(event, "action").upper()
    if action not in SUPPORTED_SIGNAL_ACTIONS:
        raise ValueError(f"unsupported persisted Pine action: {action}")
    runner_stage = _optional_text(event.get("runner_stage"))
    if action == "ADD" and runner_stage not in {"ADD_1_ATR", "ADD_2_ATR"}:
        raise ValueError("ADD reference requires an audited runner_stage")
    if action == "PARTIAL" and runner_stage != "HARVEST_3_ATR":
        raise ValueError("PARTIAL reference requires HARVEST_3_ATR runner_stage")

    signal_id = _required_text(event, "signal_id")
    return ReferenceSignal(
        symbol=_required_text(event, "symbol").upper(),
        bar_time=_timestamp(event.get("bar_time"), "bar_time"),
        action=action,
        price=_price(event.get("price")),
        entry_type=_required_text(event, "entry_type"),
        runner_stage=runner_stage,
        quantity_units=None,
        source=source,
        source_id=signal_id,
    )


def parse_shadow_book_reference_snapshot(
    book_state: Mapping[str, Any],
    *,
    expected_model_id: str,
    expected_strategy_version: str,
    expected_strategy: str = DA_TURTLE_STRATEGY,
    expected_source: str = TRADINGVIEW_PINE_SOURCE,
    expected_timeframe: str = "1D",
) -> PersistedReferenceSnapshot:
    """Convert a complete read-only monitor book into strict Pine reference signals.

    This adapter intentionally ignores PAPER execution disposition. A genuine TradingView
    strategy event remains reference evidence even when the downstream PAPER engine says
    NO_TRADE, DATA_ERROR, or another execution-layer result.
    """
    if not isinstance(book_state, Mapping):
        raise TypeError("shadow book state must be an object")

    if bool(book_state.get("scan_truncated")):
        raise ValueError("persisted Pine event scan is truncated")
    raw_events = book_state.get("events")
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
        raise TypeError("shadow book events must be a list")

    event_count_visible = int(book_state.get("event_count_visible", -1))
    event_limit = int(book_state.get("event_limit", -1))
    scan_items_evaluated = int(book_state.get("scan_items_evaluated", -1))
    if event_count_visible < 0 or event_limit < 1 or scan_items_evaluated < 0:
        raise ValueError("shadow monitor event evidence counts are invalid")
    if event_count_visible != len(raw_events):
        raise ValueError("shadow monitor event_count_visible does not match returned events")

    signals: list[ReferenceSignal] = []
    seen_signal_ids: set[str] = set()
    for raw_event in raw_events:
        if not isinstance(raw_event, Mapping):
            raise TypeError("each persisted Pine event must be an object")
        signal = _reference_signal(
            raw_event,
            expected_model_id=expected_model_id,
            expected_strategy_version=expected_strategy_version,
            expected_strategy=expected_strategy,
            expected_source=expected_source,
            expected_timeframe=expected_timeframe,
        )
        if signal.source_id in seen_signal_ids:
            raise ValueError("duplicate persisted Pine signal_id in reference evidence")
        seen_signal_ids.add(str(signal.source_id))
        signals.append(signal)

    signals.sort(key=lambda item: (item.bar_time, item.symbol, str(item.source_id)))
    return PersistedReferenceSnapshot(
        model_id=expected_model_id,
        strategy_version=expected_strategy_version,
        event_count_visible=event_count_visible,
        event_limit=event_limit,
        scan_items_evaluated=scan_items_evaluated,
        signals=tuple(signals),
    )


__all__ = [
    "DA_TURTLE_STRATEGY",
    "SUPPORTED_SIGNAL_ACTIONS",
    "TRADINGVIEW_PINE_SOURCE",
    "PersistedReferenceSnapshot",
    "parse_shadow_book_reference_snapshot",
]
