from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .pine_bar_outcome_compare import (
    BarOutcomeKind,
    BarOutcomeReport,
    ReferenceBarOutcome,
    compare_v24_bar_outcomes,
)
from .pine_parity_compare import ParityReport
from .pine_parity_evidence import (
    PARITY_EVIDENCE_SCHEMA_VERSION,
    ParityEvidenceBundle,
    evaluate_v24_evidence,
    parse_parity_evidence_bundle,
)
from .pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_STRATEGY_VERSION,
    V24Parameters,
    run_v24_parity,
)


class HistoricalReferenceError(ValueError):
    """Historical parity input is incomplete, ambiguous, or violates point-in-time lineage."""


class EarningsEvidenceState(StrEnum):
    NONE = "NONE"
    KNOWN = "KNOWN"


@dataclass(frozen=True, slots=True)
class HistoricalSourceArtifact:
    source: str
    revision: str
    sha256: str
    row_count: int


@dataclass(frozen=True, slots=True)
class HistoricalV24Reference:
    bundle: ParityEvidenceBundle
    reference_bar_outcomes: tuple[ReferenceBarOutcome, ...]
    market_artifact: HistoricalSourceArtifact
    signal_artifact: HistoricalSourceArtifact
    bar_outcome_artifact: HistoricalSourceArtifact

    @property
    def reference_id(self) -> str:
        payload = {
            "model_id": self.bundle.model_id,
            "strategy_version": self.bundle.strategy_version,
            "strategy_source_revision": self.bundle.source_revision,
            "symbol": self.bundle.symbol,
            "market_sha256": self.market_artifact.sha256,
            "signal_sha256": self.signal_artifact.sha256,
            "bar_outcome_sha256": self.bar_outcome_artifact.sha256,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalV24Evaluation:
    reference_id: str
    signal_report: ParityReport
    bar_outcome_report: BarOutcomeReport

    @property
    def exact(self) -> bool:
        return self.signal_report.exact and self.bar_outcome_report.exact


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required_text(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HistoricalReferenceError(f"{name}_REQUIRED")
    return normalized


def _timestamp(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_required_text(value, name))
    except ValueError as exc:
        raise HistoricalReferenceError(f"{name}_INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoricalReferenceError(f"{name}_MUST_BE_TIMEZONE_AWARE")
    return parsed


def _rows(text: str, required_headers: frozenset[str], artifact_name: str) -> list[dict[str, str]]:
    if not text.strip():
        raise HistoricalReferenceError(f"{artifact_name}_CSV_REQUIRED")
    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or ())
    missing = sorted(required_headers - headers)
    if missing:
        raise HistoricalReferenceError(
            f"{artifact_name}_CSV_MISSING_HEADERS:{','.join(missing)}"
        )
    return [dict(row) for row in reader]


def _artifact(source: str, revision: str, text: str, row_count: int) -> HistoricalSourceArtifact:
    return HistoricalSourceArtifact(
        source=_required_text(source, "SOURCE"),
        revision=_required_text(revision, "REVISION"),
        sha256=_sha256(text),
        row_count=row_count,
    )


def _parse_market_rows(
    text: str,
    *,
    symbol: str,
) -> tuple[list[dict[str, Any]], set[datetime], int]:
    required = frozenset(
        {
            "time",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "earnings_state",
            "earnings_actual",
            "earnings_known_at",
            "source_id",
        }
    )
    rows = _rows(text, required, "MARKET")
    if not rows:
        raise HistoricalReferenceError("MARKET_CSV_HAS_NO_ROWS")

    normalized: list[dict[str, Any]] = []
    bar_times: set[datetime] = set()
    source_ids: set[str] = set()
    previous_time: datetime | None = None
    earnings_count = 0

    for row in rows:
        row_symbol = _required_text(row.get("symbol"), "MARKET_SYMBOL").upper()
        if row_symbol != symbol:
            raise HistoricalReferenceError("MARKET_SYMBOL_MISMATCH")
        bar_time = _timestamp(row.get("time"), "MARKET_TIME")
        if previous_time is not None and bar_time <= previous_time:
            raise HistoricalReferenceError("MARKET_BARS_NOT_STRICTLY_CHRONOLOGICAL")
        previous_time = bar_time
        if bar_time in bar_times:
            raise HistoricalReferenceError("MARKET_BAR_TIME_DUPLICATE")
        bar_times.add(bar_time)

        source_id = _required_text(row.get("source_id"), "MARKET_SOURCE_ID")
        if source_id in source_ids:
            raise HistoricalReferenceError("MARKET_SOURCE_ID_DUPLICATE")
        source_ids.add(source_id)

        try:
            earnings_state = EarningsEvidenceState(
                _required_text(row.get("earnings_state"), "EARNINGS_STATE").upper()
            )
        except ValueError as exc:
            raise HistoricalReferenceError("EARNINGS_STATE_INVALID") from exc
        actual_text = str(row.get("earnings_actual") or "").strip()
        known_at_text = str(row.get("earnings_known_at") or "").strip()
        if earnings_state is EarningsEvidenceState.NONE:
            if actual_text or known_at_text:
                raise HistoricalReferenceError("EARNINGS_NONE_CANNOT_CARRY_EVENT_DATA")
            earnings_actual: float | None = None
        else:
            if not actual_text or not known_at_text:
                raise HistoricalReferenceError("EARNINGS_KNOWN_REQUIRES_ACTUAL_AND_KNOWN_AT")
            known_at = _timestamp(known_at_text, "EARNINGS_KNOWN_AT")
            if known_at > bar_time:
                raise HistoricalReferenceError("EARNINGS_EVENT_WAS_NOT_KNOWN_BY_BAR_CLOSE")
            try:
                earnings_actual = float(actual_text)
            except ValueError as exc:
                raise HistoricalReferenceError("EARNINGS_ACTUAL_NOT_NUMERIC") from exc
            earnings_count += 1

        normalized.append(
            {
                "time": bar_time.isoformat(),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "earnings_actual": earnings_actual,
            }
        )

    return normalized, bar_times, earnings_count


def _parse_signal_rows(
    text: str,
    *,
    symbol: str,
    bar_times: set[datetime],
) -> tuple[list[dict[str, Any]], dict[datetime, tuple[str, ...]]]:
    required = frozenset(
        {
            "bar_time",
            "symbol",
            "action",
            "price",
            "entry_type",
            "runner_stage",
            "quantity_units",
            "source_id",
        }
    )
    rows = _rows(text, required, "TRADINGVIEW_SIGNAL")
    normalized: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    actions_by_time: dict[datetime, list[str]] = {}
    allowed_actions = {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}

    for row in rows:
        row_symbol = _required_text(row.get("symbol"), "SIGNAL_SYMBOL").upper()
        if row_symbol != symbol:
            raise HistoricalReferenceError("SIGNAL_SYMBOL_MISMATCH")
        bar_time = _timestamp(row.get("bar_time"), "SIGNAL_BAR_TIME")
        if bar_time not in bar_times:
            raise HistoricalReferenceError("SIGNAL_BAR_TIME_NOT_PRESENT_IN_MARKET_EVIDENCE")
        action = _required_text(row.get("action"), "SIGNAL_ACTION").upper()
        if action not in allowed_actions:
            raise HistoricalReferenceError("SIGNAL_ACTION_UNSUPPORTED")
        source_id = _required_text(row.get("source_id"), "SIGNAL_SOURCE_ID")
        if source_id in source_ids:
            raise HistoricalReferenceError("SIGNAL_SOURCE_ID_DUPLICATE")
        source_ids.add(source_id)
        quantity = str(row.get("quantity_units") or "").strip()
        normalized.append(
            {
                "symbol": row_symbol,
                "bar_time": bar_time.isoformat(),
                "action": action,
                "price": row.get("price"),
                "entry_type": str(row.get("entry_type") or "NONE").strip() or "NONE",
                "runner_stage": str(row.get("runner_stage") or "").strip() or None,
                "quantity_units": None if not quantity else int(quantity),
                "source_id": source_id,
            }
        )
        actions_by_time.setdefault(bar_time, []).append(action)

    return normalized, {
        bar_time: tuple(actions) for bar_time, actions in actions_by_time.items()
    }


def _split_pipe(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    return tuple(part.strip().upper() for part in text.split("|") if part.strip())


def _parse_bar_outcomes(
    text: str,
    *,
    symbol: str,
    bar_times: set[datetime],
    signal_actions_by_time: dict[datetime, tuple[str, ...]],
) -> tuple[ReferenceBarOutcome, ...]:
    required = frozenset(
        {
            "bar_time",
            "symbol",
            "outcome_kind",
            "signal_actions",
            "rejection_reasons",
            "entry_type",
            "source_id",
        }
    )
    rows = _rows(text, required, "TRADINGVIEW_BAR_OUTCOME")
    outcomes: list[ReferenceBarOutcome] = []
    seen_times: set[datetime] = set()
    source_ids: set[str] = set()

    for row in rows:
        row_symbol = _required_text(row.get("symbol"), "BAR_OUTCOME_SYMBOL").upper()
        if row_symbol != symbol:
            raise HistoricalReferenceError("BAR_OUTCOME_SYMBOL_MISMATCH")
        bar_time = _timestamp(row.get("bar_time"), "BAR_OUTCOME_TIME")
        if bar_time not in bar_times:
            raise HistoricalReferenceError("BAR_OUTCOME_TIME_NOT_PRESENT_IN_MARKET_EVIDENCE")
        if bar_time in seen_times:
            raise HistoricalReferenceError("BAR_OUTCOME_TIME_DUPLICATE")
        seen_times.add(bar_time)
        source_id = _required_text(row.get("source_id"), "BAR_OUTCOME_SOURCE_ID")
        if source_id in source_ids:
            raise HistoricalReferenceError("BAR_OUTCOME_SOURCE_ID_DUPLICATE")
        source_ids.add(source_id)
        try:
            kind = BarOutcomeKind(
                _required_text(row.get("outcome_kind"), "BAR_OUTCOME_KIND").upper()
            )
        except ValueError as exc:
            raise HistoricalReferenceError("BAR_OUTCOME_KIND_INVALID") from exc
        outcome = ReferenceBarOutcome(
            symbol=row_symbol,
            bar_time=bar_time,
            outcome_kind=kind,
            signal_actions=_split_pipe(row.get("signal_actions")),
            rejection_reasons=_split_pipe(row.get("rejection_reasons")),
            entry_type=str(row.get("entry_type") or "NONE").strip() or "NONE",
            source_id=source_id,
        )
        expected_actions = signal_actions_by_time.get(bar_time, ())
        if outcome.signal_actions != expected_actions:
            raise HistoricalReferenceError("BAR_OUTCOME_SIGNAL_STREAM_DISAGREEMENT")
        outcomes.append(outcome)

    if seen_times != bar_times:
        raise HistoricalReferenceError("BAR_OUTCOME_COVERAGE_MUST_MATCH_EVERY_MARKET_BAR")
    return tuple(sorted(outcomes, key=lambda item: item.bar_time))


def build_historical_v24_reference(
    *,
    symbol: str,
    market_csv: str,
    tradingview_signal_csv: str,
    tradingview_bar_outcome_csv: str,
    market_source: str,
    market_revision: str,
    tradingview_source: str,
    tradingview_signal_revision: str,
    tradingview_bar_outcome_revision: str,
) -> HistoricalV24Reference:
    """Build an auditable SH24 reference only from explicit point-in-time source artifacts."""
    normalized_symbol = _required_text(symbol, "SYMBOL").upper()
    bars, bar_times, _earnings_count = _parse_market_rows(
        market_csv,
        symbol=normalized_symbol,
    )
    signals, signal_actions_by_time = _parse_signal_rows(
        tradingview_signal_csv,
        symbol=normalized_symbol,
        bar_times=bar_times,
    )
    bar_outcomes = _parse_bar_outcomes(
        tradingview_bar_outcome_csv,
        symbol=normalized_symbol,
        bar_times=bar_times,
        signal_actions_by_time=signal_actions_by_time,
    )
    bundle = parse_parity_evidence_bundle(
        {
            "schema_version": PARITY_EVIDENCE_SCHEMA_VERSION,
            "source": _required_text(tradingview_source, "TRADINGVIEW_SOURCE"),
            "source_revision": PINE_V24_SOURCE_BLOB_SHA,
            "model_id": PINE_V24_MODEL_ID,
            "strategy_version": PINE_V24_STRATEGY_VERSION,
            "symbol": normalized_symbol,
            "bars": bars,
            "reference_signals": signals,
        }
    )
    return HistoricalV24Reference(
        bundle=bundle,
        reference_bar_outcomes=bar_outcomes,
        market_artifact=_artifact(
            market_source,
            market_revision,
            market_csv,
            len(bars),
        ),
        signal_artifact=_artifact(
            tradingview_source,
            tradingview_signal_revision,
            tradingview_signal_csv,
            len(signals),
        ),
        bar_outcome_artifact=_artifact(
            tradingview_source,
            tradingview_bar_outcome_revision,
            tradingview_bar_outcome_csv,
            len(bar_outcomes),
        ),
    )


def evaluate_historical_v24_reference(
    reference: HistoricalV24Reference,
    parameters: V24Parameters | None = None,
) -> HistoricalV24Evaluation:
    """Evaluate signal and explicit bar-level parity without rewriting either source."""
    signal_report = evaluate_v24_evidence(reference.bundle, parameters)
    python_results = run_v24_parity(
        reference.bundle.symbol,
        reference.bundle.bars,
        parameters,
    )
    bar_report = compare_v24_bar_outcomes(
        reference.reference_bar_outcomes,
        python_results,
    )
    return HistoricalV24Evaluation(
        reference_id=reference.reference_id,
        signal_report=signal_report,
        bar_outcome_report=bar_report,
    )


__all__ = [
    "EarningsEvidenceState",
    "HistoricalReferenceError",
    "HistoricalSourceArtifact",
    "HistoricalV24Evaluation",
    "HistoricalV24Reference",
    "build_historical_v24_reference",
    "evaluate_historical_v24_reference",
]
