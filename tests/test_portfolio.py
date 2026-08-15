import pytest

from daily_alpha.portfolio import (
    AssetType,
    Greeks,
    PortfolioDataStatus,
    PortfolioSnapshot,
    Position,
)


def test_snapshot_aggregates_exposure_and_option_greeks():
    positions = (
        Position("AAPL", AssetType.STOCK, 10, 200, 180, sector="Technology"),
        Position(
            "AAPL 2026-10-16 220C",
            AssetType.OPTION,
            2,
            5,
            4,
            multiplier=100,
            sector="Technology",
            expiration="2026-10-16",
            greeks=Greeks(delta=0.5, gamma=0.02, theta=-0.04, vega=0.1),
        ),
    )
    snapshot = PortfolioSnapshot.create(
        snapshot_id="snap-1",
        account_id="paper-1",
        source="TEST",
        as_of="2026-08-15T12:00:00+00:00",
        cash=10_000,
        buying_power=8_000,
        positions=positions,
    )

    assert snapshot.net_liquidating_value == 13_000
    assert snapshot.gross_exposure == 3_000
    assert snapshot.net_exposure == 3_000
    assert snapshot.sector_exposure() == {"Technology": 3_000}
    assert snapshot.aggregate_greeks() == Greeks(delta=100, gamma=4, theta=-8, vega=20)
    assert snapshot.blocks_new_risk is False


def test_short_positions_preserve_net_and_gross_exposure():
    snapshot = PortfolioSnapshot.create(
        snapshot_id="snap-2",
        account_id="paper-1",
        source="TEST",
        as_of="2026-08-15T12:00:00Z",
        cash=1_000,
        buying_power=1_000,
        positions=(Position("SPY", AssetType.STOCK, -2, 500, 510),),
    )
    assert snapshot.net_exposure == -1_000
    assert snapshot.gross_exposure == 1_000


def test_reconciliation_error_downgrades_status_and_blocks_new_risk():
    snapshot = PortfolioSnapshot.create(
        snapshot_id="snap-3",
        account_id="paper-1",
        source="TEST",
        as_of="2026-08-15T12:00:00Z",
        cash=1_000,
        buying_power=1_000,
        positions=(),
        reconciliation_errors=("cash mismatch",),
    )
    assert snapshot.data_status == PortfolioDataStatus.PARTIAL
    assert snapshot.blocks_new_risk is True


def test_option_without_greeks_is_rejected_instead_of_estimated():
    with pytest.raises(ValueError, match="require Greeks"):
        Position("SPY CALL", AssetType.OPTION, 1, 2, 2, multiplier=100)


@pytest.mark.parametrize("status", [PortfolioDataStatus.PARTIAL, PortfolioDataStatus.STALE, PortfolioDataStatus.UNAVAILABLE])
def test_non_available_status_blocks_new_risk(status):
    snapshot = PortfolioSnapshot.create(
        snapshot_id="snap-4",
        account_id="paper-1",
        source="TEST",
        as_of="2026-08-15T12:00:00Z",
        cash=0,
        buying_power=0,
        positions=(),
        data_status=status,
    )
    assert snapshot.blocks_new_risk is True
