from daily_alpha.instrument_expression_research import (
    Expression,
    ExpressionInputs,
    ExpressionPolicy,
    SectorStrength,
    classify_expression,
    sgov_reserve_amount,
    split_common_risk_budget,
)


def test_required_data_error_fails_closed_before_any_fallback() -> None:
    decision = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=False,
            required_data_ok=False,
            sector_strength=SectorStrength.EXCEPTIONAL,
            sector_breadth_ok=True,
        ),
        ExpressionPolicy(allow_3x_sector_research=True),
    )

    assert decision.expression is Expression.NO_TRADE
    assert decision.reason == "REQUIRED_DATA_ERROR"


def test_qualified_r2_defaults_to_shares_without_option_quality() -> None:
    decision = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=True,
            option_quality_ok=False,
            option_dte=120,
        )
    )

    assert decision.expression is Expression.SHARES
    assert decision.option_overlay_eligible is False


def test_long_call_overlay_requires_quality_and_dte_window() -> None:
    eligible = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=True,
            option_quality_ok=True,
            option_dte=120,
        )
    )
    too_short = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=True,
            option_quality_ok=True,
            option_dte=60,
        )
    )

    assert eligible.expression is Expression.SHARES_PLUS_LONG_CALL
    assert eligible.option_overlay_eligible is True
    assert too_short.expression is Expression.SHARES


def test_sector_proxy_requires_no_stock_setup_and_confirmed_breadth() -> None:
    strong = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=False,
            sector_strength=SectorStrength.STRONG,
            sector_breadth_ok=True,
        )
    )
    weak_breadth = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=False,
            sector_strength=SectorStrength.STRONG,
            sector_breadth_ok=False,
        )
    )

    assert strong.expression is Expression.SECTOR_2X
    assert weak_breadth.expression is Expression.NO_TRADE


def test_exceptional_sector_requires_explicit_3x_research_enable() -> None:
    default = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=False,
            sector_strength=SectorStrength.EXCEPTIONAL,
            sector_breadth_ok=True,
        )
    )
    enabled = classify_expression(
        ExpressionInputs(
            individual_r2_qualified=False,
            sector_strength=SectorStrength.EXCEPTIONAL,
            sector_breadth_ok=True,
        ),
        ExpressionPolicy(allow_3x_sector_research=True),
    )

    assert default.expression is Expression.SECTOR_2X
    assert enabled.expression is Expression.SECTOR_3X


def test_common_risk_budget_split_cannot_double_risk() -> None:
    share_risk, option_risk = split_common_risk_budget(
        6250.0,
        option_fraction=0.30,
    )

    assert share_risk == 4375.0
    assert option_risk == 1875.0
    assert share_risk + option_risk == 6250.0


def test_sgov_reserve_preserves_buffer_and_excludes_borrowed_cash() -> None:
    reserve = sgov_reserve_amount(
        100_000.0,
        operational_cash_buffer=10_000.0,
        borrowed_cash=25_000.0,
    )

    assert reserve == 65_000.0


def test_sgov_reserve_never_goes_negative() -> None:
    reserve = sgov_reserve_amount(
        5_000.0,
        operational_cash_buffer=10_000.0,
    )

    assert reserve == 0.0
