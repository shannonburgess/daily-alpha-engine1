from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from .pine_forward_deployment_evidence import (
    CANONICAL_DAILY_TIMEFRAMES,
    ForwardParityBookEvidence,
    ForwardParityDeploymentEvidence,
)
from .pine_forward_event_classification import partition_forward_events
from .pine_forward_replay_provenance import ForwardReplayProvenance
from .pine_parity_compare import ParityReport, ReferenceSignal, compare_pine_signals
from .pine_v24_parity import ParitySignal

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


@dataclass(frozen=True, slots=True)
class ReceiptBoundForwardParityEvaluation:
    """Forward comparison anchored to one trusted deployment receipt identity."""

    model_id: str
    strategy_version: str
    deployment_commit_sha: str
    processor_code_sha256: str
    reference_snapshot: PersistedReferenceSnapshot
    report: ParityReport
    replay_provenance: ForwardReplayProvenance | None = None
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.reference_snapshot.model_id != self.model_id:
            raise ValueError("forward evaluation model_id does not match reference snapshot")
        if self.reference_snapshot.strategy_version != self.strategy_version:
            raise ValueError("forward evaluation strategy_version does not match reference snapshot")
        if self.report.reference_count != len(self.reference_snapshot.signals):
            raise ValueError("forward evaluation report is not bound to reference snapshot count")
        if self.replay_provenance is not None:
            if self.replay_provenance.model_id != self.model_id:
                raise ValueError("forward replay provenance crossed the requested model book")
            if self.replay_provenance.strategy_version != self.strategy_version:
                raise ValueError("forward replay provenance crossed the requested strategy version")
            if self.replay_provenance.deployment_commit_sha != self.deployment_commit_sha:
                raise ValueError("forward replay provenance deployment commit is inconsistent")
            if self.replay_provenance.processor_code_sha256 != self.processor_code_sha256:
                raise ValueError("forward replay provenance processor identity is inconsistent")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("forward parity evaluation cannot authorize trading")

    @property
    def exact(self) -> bool:
        return self.report.exact

    @property
    def replay_inputs_locked(self) -> bool:
        return self.replay_provenance is not None


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


def _timeframe_matches(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    return actual in CANONICAL_DAILY_TIMEFRAMES and expected in CANONICAL_DAILY_TIMEFRAMES


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
    if not _timeframe_matches(timeframe, expected_timeframe):
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

    PAPER execution disposition is intentionally ignored: source-signal truth remains reference
    evidence even when the downstream PAPER engine reports NO_TRADE or DATA_ERROR.
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


def parse_forward_deployment_reference_snapshot(
    book: ForwardParityBookEvidence,
    *,
    expected_model_id: str,
    expected_strategy_version: str,
) -> PersistedReferenceSnapshot:
    """Convert validated receipt evidence after removing only exact registered E2E traffic."""
    if book.account_id != expected_model_id:
        raise ValueError("deployment receipt book does not match requested model")
    partition = partition_forward_events(book)
    reference_state = {
        "events": [event.to_dict() for event in partition.reference_candidates],
        "event_count_visible": partition.reference_candidate_count,
        "event_limit": book.event_limit,
        "scan_items_evaluated": book.scan_items_evaluated,
        "scan_truncated": False,
    }
    return parse_shadow_book_reference_snapshot(
        reference_state,
        expected_model_id=expected_model_id,
        expected_strategy_version=expected_strategy_version,
        expected_timeframe="D",
    )


def evaluate_forward_deployment_reference(
    deployment: ForwardParityDeploymentEvidence,
    *,
    expected_model_id: str,
    expected_strategy_version: str,
    python_signals: Iterable[ParitySignal],
    replay_provenance: ForwardReplayProvenance | None = None,
) -> ReceiptBoundForwardParityEvaluation:
    """Compare Python signals only against exact non-E2E events in one trusted receipt."""
    if expected_model_id == "PAPER_SHADOW_V24":
        book = deployment.sh24
    elif expected_model_id == "PAPER_SHADOW_V25":
        book = deployment.sh25
    else:
        raise ValueError("requested model is not an isolated SH24/SH25 parity book")
    snapshot = parse_forward_deployment_reference_snapshot(
        book,
        expected_model_id=expected_model_id,
        expected_strategy_version=expected_strategy_version,
    )
    report = compare_pine_signals(snapshot.signals, python_signals)
    return ReceiptBoundForwardParityEvaluation(
        model_id=expected_model_id,
        strategy_version=expected_strategy_version,
        deployment_commit_sha=deployment.commit_sha,
        processor_code_sha256=deployment.processor_code_sha256,
        reference_snapshot=snapshot,
        report=report,
        replay_provenance=replay_provenance,
    )


__all__ = [
    "DA_TURTLE_STRATEGY",
    "SUPPORTED_SIGNAL_ACTIONS",
    "TRADINGVIEW_PINE_SOURCE",
    "PersistedReferenceSnapshot",
    "ReceiptBoundForwardParityEvaluation",
    "evaluate_forward_deployment_reference",
    "parse_forward_deployment_reference_snapshot",
    "parse_shadow_book_reference_snapshot",
]
