import pytest

from daily_alpha.runner import allocate_runner
from daily_alpha.sizing import SizingError


def test_runner_allocation_rounds_down_to_exact_four_unit_blocks():
    allocation = allocate_runner(9)
    assert allocation.raw_quantity == 9
    assert allocation.target_quantity == 8
    assert allocation.starter_quantity == 4
    assert allocation.add_quantity == 2
    assert allocation.harvest_quantity == 2
    assert allocation.starter_fraction == 0.5
    assert allocation.add_fraction == 0.25


def test_runner_allocation_preserves_exact_50_25_25_ratios():
    allocation = allocate_runner(12)
    assert allocation.target_quantity == 12
    assert allocation.starter_quantity == 6
    assert allocation.add_quantity == 3
    assert allocation.harvest_quantity == 3


def test_runner_requires_at_least_four_units():
    with pytest.raises(SizingError, match="4-unit runner"):
        allocate_runner(3)
