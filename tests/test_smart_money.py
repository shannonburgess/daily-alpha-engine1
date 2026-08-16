from datetime import UTC, date, datetime

from daily_alpha.smart_money import (
    CongressionalTrade,
    InstitutionalHolding,
    build_smart_money_snapshot,
    rank_congressional_acquisitions,
    rank_institutional_acquisitions,
    smart_money_bonus,
    write_smart_money_outputs,
)


def congress(
    politician,
    symbol,
    *,
    amount=10_000,
    tx=date(2026, 8, 1),
    disclosed=date(2026, 8, 10),
):
    return CongressionalTrade(
        politician=politician,
        chamber="House",
        symbol=symbol,
        issuer=symbol + " Corp",
        transaction_date=tx,
        disclosure_date=disclosed,
        transaction_type="PURCHASE",
        amount_low=amount,
        amount_high=amount,
    )


def holding(manager, cusip, shares, value, *, issuer="Issuer", symbol="", period=date(2026, 6, 30)):
    return InstitutionalHolding(
        manager_cik=manager,
        manager_name=f"Manager {manager}",
        cusip=cusip,
        issuer=issuer,
        symbol=symbol,
        period_of_report=period,
        shares=shares,
        value=value,
    )


def test_congressional_breadth_beats_single_repeated_buyer():
    trades = [
        congress("A", "AAA"),
        congress("B", "AAA"),
        congress("A", "BBB", amount=50_000),
        congress("A", "BBB", amount=50_000),
    ]
    ranked = rank_congressional_acquisitions(trades, as_of=date(2026, 8, 16))
    assert ranked[0].symbol == "AAA"
    assert ranked[0].unique_politicians == 2


def test_institutional_rank_uses_positive_share_change_not_price_change():
    previous = [
        holding("1", "AAA111111", 100, 1_000, issuer="Alpha"),
        holding("2", "BBB222222", 100, 1_000, issuer="Beta"),
    ]
    current = [
        holding("1", "AAA111111", 100, 2_000, issuer="Alpha"),
        holding("2", "BBB222222", 200, 2_000, issuer="Beta"),
        holding("3", "BBB222222", 50, 500, issuer="Beta"),
    ]
    ranked = rank_institutional_acquisitions(
        current,
        previous,
        symbol_map={"BBB222222": "BBB"},
    )
    assert [item.cusip for item in ranked] == ["BBB222222"]
    assert ranked[0].symbol == "BBB"
    assert ranked[0].new_manager_positions == 1
    assert ranked[0].managers_increasing == 2


def test_smart_money_bonus_is_bounded_and_rank_weighted():
    congressional = rank_congressional_acquisitions(
        [congress("A", "AAA"), congress("B", "AAA")],
        as_of=date(2026, 8, 16),
    )
    institutional = rank_institutional_acquisitions(
        [holding("1", "AAA111111", 200, 2_000, issuer="Alpha", symbol="AAA")],
        [],
    )
    assert smart_money_bonus("AAA", congressional, institutional) == 15.0
    assert smart_money_bonus("ZZZ", congressional, institutional) == 0.0


def test_snapshot_outputs_are_research_only(tmp_path):
    congressional = rank_congressional_acquisitions(
        [congress("A", "AAA")], as_of=date(2026, 8, 16)
    )
    institutional = rank_institutional_acquisitions(
        [holding("1", "AAA111111", 200, 2_000, issuer="Alpha", symbol="AAA")], []
    )
    snapshot = build_smart_money_snapshot(
        generated_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
        congressional=congressional,
        institutional=institutional,
        coverage={"congress": "TEST", "institutional": "TEST"},
    )
    outputs = write_smart_money_outputs(tmp_path, snapshot)
    assert all(path.exists() for path in outputs.values())
    assert snapshot.trading_authorized is False
    assert snapshot.live_trading_enabled is False
