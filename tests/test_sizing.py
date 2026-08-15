import pytest

from daily_alpha.models import InstrumentSelected
from daily_alpha.sizing import (
    PortfolioLimits,
    SizingError,
    size_long_option,
    size_stock,
)


def test_option_sizing_uses_premium_as_max_loss():
    result = size_long_option(
        premium=5.0,
        limits=PortfolioLimits(nav=1_000_000),
    )
    assert result.instrument == InstrumentSelected.OPTION
    assert result.quantity == 10
    assert result.estimated_max_loss == 5_000


def test_stock_sizing_respects_capital_limit():
    result = size_stock(
        share_price=100,
        stop_price=95,
        limits=PortfolioLimits(nav=1_000_000),
    )
    assert result.instrument == InstrumentSelected.STOCK
    assert result.quantity == 200
    assert result.capital_required == 20_000


def test_option_too_expensive_for_risk_budget():
    with pytest.raises(SizingError):
        size_long_option(
            premium=60,
            limits=PortfolioLimits(nav=1_000_000),
        )
