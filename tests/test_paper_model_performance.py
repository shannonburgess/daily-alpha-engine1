from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.paper_model_performance import (
    ForwardTradeObservation,
    MODEL_VALIDATION_FILL_BASIS,
    NoTradeObservation,
    summarize_model_performance,
    summarize_shadow_books,
)


BASE = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)


def trade(
    trade_id: str,
    *,
    account: str = "PAPER_SHADOW_V24",
    entry: float = 100.0,
    exit_: float = 102.0,
    shares: float = 10.0,
    risk: float | None = 2.0,
    max_price: float | None = 104.0,
    min_price: float | None = 99.0,
    minutes: int = 60,
    setup: str = "breakout",
    lifecycle: str = "emerging",
    sector: str = "technology",
    industry: str = "semiconductors",
) -> ForwardTradeObservation:
    return ForwardTradeObservation(
        trade_id=trade_id,
        account_id=account,
        symbol="NVDA",
        entry_at=BASE,
        exit_at=BASE + timedelta(minutes=minutes),
        entry_price=entry,
        exit_price=exit_,
        shares=shares,
        initial_risk_per_share=risk,
        max_price_after_entry=max_price,
        min_price_after_entry=min_price,
        setup_type=setup,
        lifecycle_stage=lifecycle,
        sector=sector,
        industry=industry,
        exit_reason="signal_exit",
    )


def no_trade(
    event_id: str,
    *,
    account: str = "PAPER_SHADOW_V24",
    reason: str = "SECTOR_DATA_UNVERIFIED",
) -> NoTradeObservation:
    return NoTradeObservation(
        event_id=event_id,
        account_id=account,
        symbol="DINO",
        observed_at=BASE,
        reason=reason,
        setup_type="entry_long",
        lifecycle_stage="leader",
        sector="energy",
        industry="oil_gas",
    )


def test_no_closed_trades_remain_explicitly_unavailable() -> None:
    summary = summarize_model_performance(
        "PAPER_SHADOW_V24",
        [],
        [no_trade("evt-1"), no_trade("evt-2")],
    )

    assert summary.n == 0
    assert summary.win_rate is None
    assert summary.expectancy_r is None
    assert summary.profit_factor is None
    assert summary.cumulative_r is None
    assert summary.average_holding_minutes is None
    assert summary.rejection_count == 2
    assert summary.rejection_reasons == {"SECTOR_DATA_UNVERIFIED": 2}
    assert summary.evidence_status == "NO_CLOSED_TRADES"
    assert summary.promotion_authorized is False
    assert summary.trading_authorized is False
    assert summary.live_trading_enabled is False


def test_summary_calculates_requested_forward_metrics() -> None:
    records = [
        trade("1", exit_=104.0, max_price=106.0, min_price=99.0, minutes=30),
        trade("2", exit_=98.0, max_price=101.0, min_price=97.0, minutes=90),
        trade("3", exit_=102.0, max_price=105.0, min_price=98.0, minutes=60),
    ]
    summary = summarize_model_performance("PAPER_SHADOW_V24", records)

    assert summary.n == 3
    assert summary.wins == 2
    assert summary.losses == 1
    assert summary.win_rate == pytest.approx(2 / 3)
    assert summary.cumulative_model_pnl == pytest.approx(40.0)
    assert summary.average_winner_pnl == pytest.approx(30.0)
    assert summary.average_loser_pnl == pytest.approx(-20.0)
    assert summary.profit_factor == pytest.approx(3.0)
    assert summary.cumulative_r == pytest.approx(2.0)
    assert summary.expectancy_r == pytest.approx(2 / 3)
    assert summary.average_winner_r == pytest.approx(1.5)
    assert summary.average_loser_r == pytest.approx(-1.0)
    assert summary.max_drawdown_r == pytest.approx(1.0)
    assert summary.max_drawdown_pnl == pytest.approx(20.0)
    assert summary.average_mfe_r == pytest.approx((3.0 + 0.5 + 2.5) / 3)
    assert summary.average_mae_r == pytest.approx((-0.5 - 1.5 - 1.0) / 3)
    assert summary.average_holding_minutes == pytest.approx(60.0)
    assert summary.evidence_status == "SMALL_SAMPLE_DESCRIPTIVE_ONLY"


def test_rejections_do_not_increment_trade_n() -> None:
    summary = summarize_model_performance(
        "PAPER_SHADOW_V24",
        [trade("1")],
        [no_trade("evt-1"), no_trade("evt-2", reason="LIQUIDITY_FILTERED")],
    )

    assert summary.n == 1
    assert summary.rejection_count == 2
    assert summary.rejection_reasons == {
        "LIQUIDITY_FILTERED": 1,
        "SECTOR_DATA_UNVERIFIED": 1,
    }


def test_r_and_path_coverage_are_not_fabricated() -> None:
    records = [
        trade("complete"),
        trade("missing", risk=None, max_price=None, min_price=None),
    ]
    summary = summarize_model_performance("PAPER_SHADOW_V24", records)

    assert summary.n == 2
    assert summary.r_observations == 1
    assert summary.r_coverage == pytest.approx(0.5)
    assert summary.expectancy_r == pytest.approx(1.0)
    assert summary.mfe_observations == 1
    assert summary.mae_observations == 1
    assert summary.evidence_status == "R_EVIDENCE_INCOMPLETE"


def test_slices_preserve_setup_lifecycle_sector_and_industry() -> None:
    records = [
        trade("1", setup="breakout", lifecycle="emerging", sector="technology"),
        trade(
            "2",
            exit_=98.0,
            setup="re_entry",
            lifecycle="leader",
            sector="energy",
            industry="oil_gas",
        ),
    ]
    summary = summarize_model_performance("PAPER_SHADOW_V24", records)

    assert summary.by_setup_type["BREAKOUT"].n == 1
    assert summary.by_setup_type["RE_ENTRY"].n == 1
    assert summary.by_lifecycle_stage["EMERGING"].n == 1
    assert summary.by_lifecycle_stage["LEADER"].n == 1
    assert summary.by_sector["TECHNOLOGY"].expectancy_r == pytest.approx(1.0)
    assert summary.by_sector["ENERGY"].expectancy_r == pytest.approx(-1.0)
    assert summary.by_industry["SEMICONDUCTORS"].n == 1
    assert summary.by_industry["OIL_GAS"].n == 1


def test_shadow_books_are_strictly_separated() -> None:
    books = summarize_shadow_books(
        [
            trade("v24", account="PAPER_SHADOW_V24", exit_=104.0),
            trade("v25", account="PAPER_SHADOW_V25", exit_=98.0),
        ],
        [
            no_trade("e24", account="PAPER_SHADOW_V24"),
            no_trade("e25", account="PAPER_SHADOW_V25", reason="EARNINGS_RISK"),
        ],
    )

    assert books["PAPER_SHADOW_V24"].n == 1
    assert books["PAPER_SHADOW_V24"].wins == 1
    assert books["PAPER_SHADOW_V24"].rejection_reasons == {"SECTOR_DATA_UNVERIFIED": 1}
    assert books["PAPER_SHADOW_V25"].n == 1
    assert books["PAPER_SHADOW_V25"].losses == 1
    assert books["PAPER_SHADOW_V25"].rejection_reasons == {"EARNINGS_RISK": 1}


def test_duplicate_trade_and_event_ids_fail_closed() -> None:
    with pytest.raises(ValueError, match="DUPLICATE_TRADE_ID"):
        summarize_model_performance("PAPER_SHADOW_V24", [trade("dup"), trade("dup")])

    with pytest.raises(ValueError, match="DUPLICATE_NO_TRADE_EVENT_ID"):
        summarize_model_performance(
            "PAPER_SHADOW_V24",
            [],
            [no_trade("dup"), no_trade("dup")],
        )


def test_cross_book_contamination_fails_closed() -> None:
    with pytest.raises(ValueError, match="TRADE_ACCOUNT_MISMATCH"):
        summarize_model_performance(
            "PAPER_SHADOW_V24",
            [trade("wrong", account="PAPER_SHADOW_V25")],
        )

    with pytest.raises(ValueError, match="NO_TRADE_ACCOUNT_MISMATCH"):
        summarize_model_performance(
            "PAPER_SHADOW_V24",
            [],
            [no_trade("wrong", account="PAPER_SHADOW_V25")],
        )


def test_model_validation_fill_cannot_be_misrepresented_as_brokerage_fill() -> None:
    assert trade("basis").fill_basis == MODEL_VALIDATION_FILL_BASIS

    with pytest.raises(ValueError, match="MUST_NOT_BE_BROKERAGE_FILL"):
        ForwardTradeObservation(
            trade_id="bad",
            account_id="PAPER_SHADOW_V24",
            symbol="NVDA",
            entry_at=BASE,
            exit_at=BASE + timedelta(minutes=1),
            entry_price=100.0,
            exit_price=101.0,
            shares=1.0,
            brokerage_fill=True,
        )


def test_new_model_validation_observation_is_stock_only() -> None:
    with pytest.raises(ValueError, match="MUST_BE_STOCK"):
        ForwardTradeObservation(
            trade_id="option",
            account_id="PAPER_SHADOW_V24",
            symbol="NVDA",
            entry_at=BASE,
            exit_at=BASE + timedelta(minutes=1),
            entry_price=100.0,
            exit_price=101.0,
            shares=1.0,
            instrument="OPTION",
        )


def test_naive_or_invalid_time_and_price_evidence_fails_closed() -> None:
    with pytest.raises(ValueError, match="ENTRY_AT_MUST_BE_TIMEZONE_AWARE"):
        ForwardTradeObservation(
            trade_id="naive",
            account_id="PAPER_SHADOW_V24",
            symbol="NVDA",
            entry_at=BASE.replace(tzinfo=None),
            exit_at=BASE + timedelta(minutes=1),
            entry_price=100.0,
            exit_price=101.0,
            shares=1.0,
        )

    with pytest.raises(ValueError, match="PRICES_AND_SHARES_MUST_BE_POSITIVE"):
        trade("bad-price", entry=0.0)
