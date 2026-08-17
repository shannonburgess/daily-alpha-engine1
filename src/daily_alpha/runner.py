"""Canonical 50/25/25 runner allocation helpers for paper trading."""

from __future__ import annotations

from dataclasses import dataclass

from .sizing import SizingError


@dataclass(frozen=True)
class RunnerAllocation:
    """Integer-unit implementation of the canonical 50/25/25 lifecycle.

    The raw risk-sized quantity is conservatively rounded down to a multiple of
    four so the paper ledger can represent the strategy exactly with whole
    contracts/shares: 50% starter, 25% add #1, 25% add #2, then a 25% harvest
    of the fully built target.
    """

    raw_quantity: int
    target_quantity: int
    starter_quantity: int
    add_quantity: int
    harvest_quantity: int

    @property
    def starter_fraction(self) -> float:
        return self.starter_quantity / self.target_quantity

    @property
    def add_fraction(self) -> float:
        return self.add_quantity / self.target_quantity


def allocate_runner(raw_quantity: int) -> RunnerAllocation:
    if raw_quantity <= 0:
        raise SizingError("Runner raw quantity must be positive")

    target = (raw_quantity // 4) * 4
    if target < 4:
        raise SizingError(
            "Risk budget is too small for the canonical 4-unit runner lifecycle"
        )

    unit = target // 4
    return RunnerAllocation(
        raw_quantity=raw_quantity,
        target_quantity=target,
        starter_quantity=unit * 2,
        add_quantity=unit,
        harvest_quantity=unit,
    )
