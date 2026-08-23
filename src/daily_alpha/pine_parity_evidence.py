from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Any

from .pine_parity_compare import ParityReport, ReferenceSignal, compare_pine_signals
from .pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_STRATEGY_VERSION,
    DailyBar,
    V24Parameters,
    run_v24_parity,
)

PARITY_EVIDENCE_SCHEMA_VERSION = "2026-08-23-v1"


@dataclass(frozen=True, slots=True)
class ParityEvidenceBundle:
    schema_version: str
    source: str
    source_revision: str
    model_id: str
    strategy_version: str
    symbol: str
    bars: tuple[DailyBar, ...]
    reference_signals: tuple[ReferenceSignal, ...]


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    value = str(payload.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _number(payload: Mapping[str, Any], name: str, *, default: float = 0.0) -> float:
    value = payload.get(name, default)
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _bar(payload: Any) -> DailyBar:
    if not isinstance(payload, Mapping):
        raise TypeError("each bar must be an object")
    earnings_actual = payload.get("earnings_actual")
    return DailyBar(
        time=_timestamp(payload.get("time"), "bar.time"),
        open=_number(payload, "open"),
        high=_number(payload, "high"),
        low=_number(payload, "low"),
        close=_number(payload, "close"),
        volume=_number(payload, "volume"),
        earnings_actual=(
            None if earnings_actual is None else _number(payload, "earnings_actual")
        ),
    )


def _reference(payload: Any, *, symbol: str, source: str) -> ReferenceSignal:
    if not isinstance(payload, Mapping):
        raise TypeError("each reference signal must be an object")
    quantity = payload.get("quantity_units")
    return ReferenceSignal(
        symbol=str(payload.get("symbol") or symbol),
        bar_time=_timestamp(payload.get("bar_time"), "reference.bar_time"),
        action=_required_text(payload, "action"),
        price=_number(payload, "price"),
        entry_type=str(payload.get("entry_type") or "NONE"),
        runner_stage=(
            None
            if payload.get("runner_stage") in {None, ""}
            else str(payload.get("runner_stage"))
        ),
        quantity_units=None if quantity is None else int(quantity),
        source=source,
        source_id=(
            None if payload.get("source_id") in {None, ""} else str(payload["source_id"])
        ),
    )


def parse_parity_evidence_bundle(payload: Mapping[str, Any]) -> ParityEvidenceBundle:
    """Validate a point-in-time Pine reference bundle without fetching or retuning data."""
    if not isinstance(payload, Mapping):
        raise TypeError("parity evidence bundle must be an object")
    schema_version = _required_text(payload, "schema_version")
    if schema_version != PARITY_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported parity evidence schema_version")
    source = _required_text(payload, "source")
    source_revision = _required_text(payload, "source_revision")
    model_id = _required_text(payload, "model_id")
    strategy_version = _required_text(payload, "strategy_version")
    symbol = _required_text(payload, "symbol").upper()
    raw_bars = payload.get("bars")
    raw_reference = payload.get("reference_signals")
    if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, (str, bytes)):
        raise TypeError("bars must be a list")
    if not isinstance(raw_reference, Sequence) or isinstance(raw_reference, (str, bytes)):
        raise TypeError("reference_signals must be a list")
    bars = tuple(_bar(item) for item in raw_bars)
    if not bars:
        raise ValueError("bars cannot be empty")
    for previous, current in pairwise(bars):
        if current.time <= previous.time:
            raise ValueError("bars must be strictly chronological")
    references = tuple(
        _reference(item, symbol=symbol, source=source) for item in raw_reference
    )
    if any(item.symbol.upper() != symbol for item in references):
        raise ValueError("reference signal symbol must match bundle symbol")
    return ParityEvidenceBundle(
        schema_version=schema_version,
        source=source,
        source_revision=source_revision,
        model_id=model_id,
        strategy_version=strategy_version,
        symbol=symbol,
        bars=bars,
        reference_signals=references,
    )


def evaluate_v24_evidence(
    bundle: ParityEvidenceBundle,
    parameters: V24Parameters | None = None,
    *,
    price_abs_tolerance: float = 1e-8,
    price_rel_tolerance: float = 1e-9,
) -> ParityReport:
    """Run frozen SH24 Python replay against a provenance-locked Pine reference bundle."""
    if bundle.model_id != PINE_V24_MODEL_ID:
        raise ValueError("bundle model_id is not SH24 CONTROL")
    if bundle.strategy_version != PINE_V24_STRATEGY_VERSION:
        raise ValueError("bundle strategy_version is not v2.4")
    results = run_v24_parity(bundle.symbol, bundle.bars, parameters)
    python_signals = tuple(signal for result in results for signal in result.signals)
    return compare_pine_signals(
        bundle.reference_signals,
        python_signals,
        price_abs_tolerance=price_abs_tolerance,
        price_rel_tolerance=price_rel_tolerance,
    )


__all__ = [
    "PARITY_EVIDENCE_SCHEMA_VERSION",
    "ParityEvidenceBundle",
    "evaluate_v24_evidence",
    "parse_parity_evidence_bundle",
]
