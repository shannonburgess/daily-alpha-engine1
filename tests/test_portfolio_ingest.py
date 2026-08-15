from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.portfolio import Greeks, PortfolioDataStatus
from daily_alpha.portfolio_ingest import DuplicateSnapshotError, PortfolioSnapshotIngestor


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def payload() -> dict:
    return {
        "snapshot_id": "snapshot-1",
        "account_id": "paper-1",
        "source": "BROKER_TEST",
        "as_of": "2026-08-15T11:55:00+00:00",
        "cash": 10_000,
        "buying_power": 8_000,
        "reported_position_count": 1,
        "reported_net_liquidating_value": 10_500,
        "positions": [
            {
                "symbol": "SPY 2026-10-16 700C",
                "asset_type": "OPTION",
                "quantity": 1,
                "mark": 5,
                "cost_basis": 4,
                "multiplier": 100,
                "sector": "ETF",
                "expiration": "2026-10-16",
                "greeks": {"delta": 0.5, "gamma": 0.02, "theta": -0.04, "vega": 0.1},
            }
        ],
    }


def test_ingests_fresh_reconciled_snapshot():
    result = PortfolioSnapshotIngestor().ingest(payload(), now=NOW)
    assert result.snapshot.data_status == PortfolioDataStatus.AVAILABLE
    assert result.snapshot.blocks_new_risk is False
    assert result.snapshot.net_liquidating_value == 10_500
    assert result.snapshot.aggregate_greeks() == Greeks(50, 2, -4, 10)
    assert len(result.content_hash) == 64


def test_duplicate_payload_is_rejected_idempotently():
    ingestor = PortfolioSnapshotIngestor()
    ingestor.ingest(payload(), now=NOW)
    with pytest.raises(DuplicateSnapshotError):
        ingestor.ingest(payload(), now=NOW)


def test_stale_snapshot_blocks_new_risk():
    old = payload()
    old["as_of"] = "2026-08-15T11:00:00+00:00"
    result = PortfolioSnapshotIngestor(max_age=timedelta(minutes=15)).ingest(old, now=NOW)
    assert result.snapshot.data_status == PortfolioDataStatus.STALE
    assert result.snapshot.blocks_new_risk is True


def test_reconciliation_mismatch_is_partial_and_blocks_risk():
    mismatched = payload()
    mismatched["reported_position_count"] = 2
    mismatched["reported_net_liquidating_value"] = 12_000
    result = PortfolioSnapshotIngestor().ingest(mismatched, now=NOW)
    assert result.snapshot.data_status == PortfolioDataStatus.PARTIAL
    assert len(result.snapshot.reconciliation_errors) == 2
    assert result.snapshot.blocks_new_risk is True


def test_missing_option_greeks_is_rejected_not_estimated():
    missing = payload()
    del missing["positions"][0]["greeks"]
    with pytest.raises(ValueError, match="require Greeks"):
        PortfolioSnapshotIngestor().ingest(missing, now=NOW)


def test_naive_timestamp_is_rejected():
    naive = payload()
    naive["as_of"] = "2026-08-15T11:55:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        PortfolioSnapshotIngestor().ingest(naive, now=NOW)
