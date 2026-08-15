from datetime import UTC, datetime, timedelta

from daily_alpha.data_quality import DataQualityGate, DataStatus, FailureCode, RunHealth

NOW = datetime(2026, 8, 15, 13, 0, tzinfo=UTC)
REQUIRED = frozenset({"symbol", "signal", "signal_date"})


def test_valid_csv_records_hash_lineage_and_permits_decisions():
    result = DataQualityGate().assess_csv(
        source="OVTLYR",
        file_name="2026-08-15.csv",
        content=b"symbol,signal,signal_date\nAAPL,BUY,2026-08-14\n",
        as_of=NOW - timedelta(hours=12),
        required_columns=REQUIRED,
        received_at=NOW,
    )
    assert result.status == DataStatus.DATA_OK
    assert result.permits_decisions is True
    assert result.total_rows == result.valid_rows == 1
    assert len(result.content_hash) == 64


def test_identical_file_is_deduplicated():
    gate = DataQualityGate()
    kwargs = {
        "source": "OVTLYR",
        "file_name": "daily.csv",
        "content": b"symbol,signal,signal_date\nAAPL,BUY,2026-08-14\n",
        "as_of": NOW,
        "required_columns": REQUIRED,
        "received_at": NOW,
    }
    gate.assess_csv(**kwargs)
    duplicate = gate.assess_csv(**kwargs)
    assert duplicate.status == DataStatus.DUPLICATE_DATA
    assert duplicate.failure_codes == (FailureCode.DUPLICATE_FILE,)


def test_stale_file_fails_closed():
    result = DataQualityGate(max_age=timedelta(hours=36)).assess_csv(
        source="OVTLYR",
        file_name="old.csv",
        content=b"symbol,signal,signal_date\nAAPL,BUY,2026-08-10\n",
        as_of=NOW - timedelta(hours=48),
        required_columns=REQUIRED,
        received_at=NOW,
    )
    assert result.status == DataStatus.STALE_DATA
    assert result.permits_decisions is False


def test_missing_columns_is_data_error():
    result = DataQualityGate().assess_csv(
        source="OVTLYR",
        file_name="bad.csv",
        content=b"symbol,signal\nAAPL,BUY\n",
        as_of=NOW,
        required_columns=REQUIRED,
        received_at=NOW,
    )
    assert result.status == DataStatus.DATA_ERROR
    assert FailureCode.MISSING_COLUMNS in result.failure_codes


def test_duplicate_symbols_are_partial_and_reported():
    result = DataQualityGate().assess_csv(
        source="OVTLYR",
        file_name="dupes.csv",
        content=b"symbol,signal,signal_date\nAAPL,BUY,2026-08-14\nAAPL,BUY,2026-08-14\n",
        as_of=NOW,
        required_columns=REQUIRED,
        received_at=NOW,
    )
    assert result.status == DataStatus.PARTIAL_DATA
    assert result.duplicate_symbols == ("AAPL",)


def test_run_health_requires_clean_data_and_zero_rejections():
    run = RunHealth(
        "run-1",
        "ovtlyr-0530-pst",
        NOW.isoformat(),
        NOW.isoformat(),
        NOW.isoformat(),
        DataStatus.DATA_OK,
        100,
        1,
    )
    assert run.healthy is False
