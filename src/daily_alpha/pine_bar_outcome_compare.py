from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .pine_v24_parity import V24BarResult


class BarOutcomeKind(StrEnum):
    SIGNAL = "SIGNAL"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"


class BarOutcomeMismatchKind(StrEnum):
    MISSING_PYTHON_BAR = "MISSING_PYTHON_BAR"
    EXTRA_PYTHON_BAR = "EXTRA_PYTHON_BAR"
    OUTCOME_KIND_MISMATCH = "OUTCOME_KIND_MISMATCH"
    SIGNAL_ACTIONS_MISMATCH = "SIGNAL_ACTIONS_MISMATCH"
    REJECTION_REASONS_MISMATCH = "REJECTION_REASONS_MISMATCH"
    ENTRY_TYPE_MISMATCH = "ENTRY_TYPE_MISMATCH"


_ALLOWED_SIGNAL_ACTIONS = frozenset({"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"})


@dataclass(frozen=True, slots=True)
class ReferenceBarOutcome:
    """Explicit Pine bar-level truth; absence of a signal is never inferred as NO_TRADE."""

    symbol: str
    bar_time: datetime
    outcome_kind: BarOutcomeKind
    signal_actions: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    entry_type: str = "NONE"
    source_id: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if self.bar_time.tzinfo is None or self.bar_time.utcoffset() is None:
            raise ValueError("bar_time must be timezone-aware")
        actions = tuple(action.strip().upper() for action in self.signal_actions)
        reasons = tuple(reason.strip().upper() for reason in self.rejection_reasons)
        if any(not action for action in actions):
            raise ValueError("signal_actions cannot contain blank values")
        if any(action not in _ALLOWED_SIGNAL_ACTIONS for action in actions):
            raise ValueError("signal_actions contains an unsupported action")
        if any(not reason for reason in reasons):
            raise ValueError("rejection_reasons cannot contain blank values")
        if len(set(actions)) != len(actions):
            raise ValueError("signal_actions must be unique within a bar")
        if len(set(reasons)) != len(reasons):
            raise ValueError("rejection_reasons must be unique within a bar")
        entry_type = self.entry_type.strip().upper() or "NONE"
        if self.outcome_kind is BarOutcomeKind.SIGNAL:
            if not actions:
                raise ValueError("SIGNAL outcome requires signal_actions")
            if reasons:
                raise ValueError("SIGNAL outcome cannot carry rejection_reasons")
        elif self.outcome_kind is BarOutcomeKind.REJECTED:
            if actions:
                raise ValueError("REJECTED outcome cannot carry signal_actions")
            if not reasons:
                raise ValueError("REJECTED outcome requires rejection_reasons")
        elif actions or reasons:
            raise ValueError("NO_TRADE outcome cannot carry signals or rejection reasons")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "signal_actions", actions)
        object.__setattr__(self, "rejection_reasons", reasons)
        object.__setattr__(self, "entry_type", entry_type)
        if self.source_id is not None:
            source_id = self.source_id.strip()
            if not source_id:
                raise ValueError("source_id cannot be blank")
            object.__setattr__(self, "source_id", source_id)


@dataclass(frozen=True, slots=True)
class BarOutcomeMismatch:
    kind: BarOutcomeMismatchKind
    symbol: str
    bar_time: datetime
    expected: str | tuple[str, ...] | None
    actual: str | tuple[str, ...] | None
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class BarOutcomeReport:
    reference_count: int
    python_count: int
    exact_bar_count: int
    mismatch_count: int
    mismatches: tuple[BarOutcomeMismatch, ...]

    @property
    def exact(self) -> bool:
        return self.mismatch_count == 0 and self.reference_count == self.python_count


def _python_outcome(result: Any) -> ReferenceBarOutcome:
    actions = tuple(signal.action for signal in result.signals)
    if actions:
        kind = BarOutcomeKind.SIGNAL
        reasons: tuple[str, ...] = ()
    elif result.rejection_reasons:
        kind = BarOutcomeKind.REJECTED
        reasons = tuple(result.rejection_reasons)
    else:
        kind = BarOutcomeKind.NO_TRADE
        reasons = ()
    return ReferenceBarOutcome(
        symbol=result.symbol,
        bar_time=result.bar_time,
        outcome_kind=kind,
        signal_actions=actions,
        rejection_reasons=reasons,
        entry_type=result.entry_type,
    )


def compare_bar_outcomes(
    reference: Iterable[ReferenceBarOutcome],
    python_results: Iterable[Any],
) -> BarOutcomeReport:
    """Compare explicit Pine bar outcomes for any parity engine with the shared result shape."""
    reference_items = tuple(reference)
    python_items = tuple(_python_outcome(result) for result in python_results)

    def keyed(
        items: tuple[ReferenceBarOutcome, ...],
        name: str,
    ) -> dict[tuple[str, datetime], ReferenceBarOutcome]:
        output: dict[tuple[str, datetime], ReferenceBarOutcome] = {}
        for item in items:
            key = (item.symbol, item.bar_time)
            if key in output:
                raise ValueError(
                    f"duplicate {name} bar outcome for "
                    f"{item.symbol} {item.bar_time.isoformat()}"
                )
            output[key] = item
        return output

    expected = keyed(reference_items, "reference")
    actual = keyed(python_items, "python")
    mismatches: list[BarOutcomeMismatch] = []
    exact_bars = 0

    for key in sorted(set(expected) | set(actual), key=lambda value: (value[1], value[0])):
        ref = expected.get(key)
        py = actual.get(key)
        symbol, bar_time = key
        if ref is None:
            mismatches.append(
                BarOutcomeMismatch(
                    BarOutcomeMismatchKind.EXTRA_PYTHON_BAR,
                    symbol,
                    bar_time,
                    None,
                    py.outcome_kind.value if py is not None else None,
                )
            )
            continue
        if py is None:
            mismatches.append(
                BarOutcomeMismatch(
                    BarOutcomeMismatchKind.MISSING_PYTHON_BAR,
                    symbol,
                    bar_time,
                    ref.outcome_kind.value,
                    None,
                    ref.source_id,
                )
            )
            continue

        before = len(mismatches)
        if ref.outcome_kind is not py.outcome_kind:
            mismatches.append(
                BarOutcomeMismatch(
                    BarOutcomeMismatchKind.OUTCOME_KIND_MISMATCH,
                    symbol,
                    bar_time,
                    ref.outcome_kind.value,
                    py.outcome_kind.value,
                    ref.source_id,
                )
            )
        if ref.signal_actions != py.signal_actions:
            mismatches.append(
                BarOutcomeMismatch(
                    BarOutcomeMismatchKind.SIGNAL_ACTIONS_MISMATCH,
                    symbol,
                    bar_time,
                    ref.signal_actions,
                    py.signal_actions,
                    ref.source_id,
                )
            )
        if ref.rejection_reasons != py.rejection_reasons:
            mismatches.append(
                BarOutcomeMismatch(
                    BarOutcomeMismatchKind.REJECTION_REASONS_MISMATCH,
                    symbol,
                    bar_time,
                    ref.rejection_reasons,
                    py.rejection_reasons,
                    ref.source_id,
                )
            )
        if ref.entry_type != py.entry_type:
            mismatches.append(
                BarOutcomeMismatch(
                    BarOutcomeMismatchKind.ENTRY_TYPE_MISMATCH,
                    symbol,
                    bar_time,
                    ref.entry_type,
                    py.entry_type,
                    ref.source_id,
                )
            )
        if len(mismatches) == before:
            exact_bars += 1

    return BarOutcomeReport(
        reference_count=len(reference_items),
        python_count=len(python_items),
        exact_bar_count=exact_bars,
        mismatch_count=len(mismatches),
        mismatches=tuple(mismatches),
    )


def compare_v24_bar_outcomes(
    reference: Iterable[ReferenceBarOutcome],
    python_results: Iterable[V24BarResult],
) -> BarOutcomeReport:
    """Backward-compatible SH24 wrapper over the shared bar-outcome comparator."""
    return compare_bar_outcomes(reference, python_results)


__all__ = [
    "BarOutcomeKind",
    "BarOutcomeMismatch",
    "BarOutcomeMismatchKind",
    "BarOutcomeReport",
    "ReferenceBarOutcome",
    "compare_bar_outcomes",
    "compare_v24_bar_outcomes",
]
