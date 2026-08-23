from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import isclose, isfinite
from typing import Literal

from daily_alpha.pine_v24_parity import ParitySignal

MismatchKind = Literal[
    "MISSING_PYTHON_SIGNAL",
    "EXTRA_PYTHON_SIGNAL",
    "ACTION_MISMATCH",
    "PRICE_MISMATCH",
    "ENTRY_TYPE_MISMATCH",
    "RUNNER_STAGE_MISMATCH",
    "QUANTITY_MISMATCH",
]


@dataclass(frozen=True, slots=True)
class ReferenceSignal:
    """Frozen TradingView/Pine event used only as a parity reference."""

    symbol: str
    bar_time: datetime
    action: str
    price: float
    entry_type: str = "NONE"
    runner_stage: str | None = None
    quantity_units: int | None = None
    source: str = "TRADINGVIEW"
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.bar_time.tzinfo is None:
            raise ValueError("bar_time must be timezone-aware")
        if not isfinite(float(self.price)):
            raise ValueError("price must be finite")


@dataclass(frozen=True, slots=True)
class ParityMismatch:
    kind: MismatchKind
    symbol: str
    bar_time: datetime
    expected_action: str | None
    actual_action: str | None
    expected_value: str | float | int | None = None
    actual_value: str | float | int | None = None
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class ParityReport:
    reference_count: int
    python_count: int
    exact_match_count: int
    mismatch_count: int
    mismatches: tuple[ParityMismatch, ...]

    @property
    def exact(self) -> bool:
        return self.mismatch_count == 0 and self.reference_count == self.python_count

    @property
    def exact_match_rate(self) -> float:
        denominator = max(self.reference_count, self.python_count)
        return 1.0 if denominator == 0 else self.exact_match_count / denominator


def _key(symbol: str, bar_time: datetime) -> tuple[str, datetime]:
    return symbol.strip().upper(), bar_time


def compare_pine_signals(
    reference: Iterable[ReferenceSignal],
    python_signals: Iterable[ParitySignal],
    *,
    price_abs_tolerance: float = 1e-8,
    price_rel_tolerance: float = 1e-9,
) -> ParityReport:
    """Compare Pine reference events to deterministic Python events without retuning either side."""
    if price_abs_tolerance < 0 or price_rel_tolerance < 0:
        raise ValueError("price tolerances must be non-negative")

    reference_items = tuple(reference)
    python_items = tuple(python_signals)
    ref_by_key: dict[tuple[str, datetime], list[ReferenceSignal]] = defaultdict(list)
    py_by_key: dict[tuple[str, datetime], list[ParitySignal]] = defaultdict(list)
    for item in reference_items:
        ref_by_key[_key(item.symbol, item.bar_time)].append(item)
    for item in python_items:
        py_by_key[_key(item.symbol, item.bar_time)].append(item)

    mismatches: list[ParityMismatch] = []
    exact_matches = 0
    all_keys = sorted(set(ref_by_key) | set(py_by_key), key=lambda value: (value[1], value[0]))

    for symbol, bar_time in all_keys:
        expected = ref_by_key[(symbol, bar_time)]
        actual = py_by_key[(symbol, bar_time)]
        pair_count = min(len(expected), len(actual))

        for index in range(pair_count):
            ref = expected[index]
            py = actual[index]
            before = len(mismatches)
            if ref.action != py.action:
                mismatches.append(
                    ParityMismatch(
                        "ACTION_MISMATCH",
                        symbol,
                        bar_time,
                        ref.action,
                        py.action,
                        source_id=ref.source_id,
                    )
                )
            if not isclose(
                ref.price,
                py.price,
                rel_tol=price_rel_tolerance,
                abs_tol=price_abs_tolerance,
            ):
                mismatches.append(
                    ParityMismatch(
                        "PRICE_MISMATCH",
                        symbol,
                        bar_time,
                        ref.action,
                        py.action,
                        ref.price,
                        py.price,
                        ref.source_id,
                    )
                )
            if ref.entry_type != py.entry_type:
                mismatches.append(
                    ParityMismatch(
                        "ENTRY_TYPE_MISMATCH",
                        symbol,
                        bar_time,
                        ref.action,
                        py.action,
                        ref.entry_type,
                        py.entry_type,
                        ref.source_id,
                    )
                )
            if ref.runner_stage != py.runner_stage:
                mismatches.append(
                    ParityMismatch(
                        "RUNNER_STAGE_MISMATCH",
                        symbol,
                        bar_time,
                        ref.action,
                        py.action,
                        ref.runner_stage,
                        py.runner_stage,
                        ref.source_id,
                    )
                )
            if ref.quantity_units is not None and ref.quantity_units != py.quantity_units:
                mismatches.append(
                    ParityMismatch(
                        "QUANTITY_MISMATCH",
                        symbol,
                        bar_time,
                        ref.action,
                        py.action,
                        ref.quantity_units,
                        py.quantity_units,
                        ref.source_id,
                    )
                )
            if len(mismatches) == before:
                exact_matches += 1

        for ref in expected[pair_count:]:
            mismatches.append(
                ParityMismatch(
                    "MISSING_PYTHON_SIGNAL",
                    symbol,
                    bar_time,
                    ref.action,
                    None,
                    source_id=ref.source_id,
                )
            )
        for py in actual[pair_count:]:
            mismatches.append(
                ParityMismatch(
                    "EXTRA_PYTHON_SIGNAL",
                    symbol,
                    bar_time,
                    None,
                    py.action,
                )
            )

    return ParityReport(
        reference_count=len(reference_items),
        python_count=len(python_items),
        exact_match_count=exact_matches,
        mismatch_count=len(mismatches),
        mismatches=tuple(mismatches),
    )
