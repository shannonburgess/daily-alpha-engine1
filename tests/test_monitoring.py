import pytest

from daily_alpha.data_quality import DataStatus
from daily_alpha.monitoring import (
    AlertSeverity,
    DependencyCheck,
    DependencyStatus,
    RunMonitor,
    RunStatus,
)


def dependency(name="OVTLYR", status=DependencyStatus.HEALTHY, critical=True):
    return DependencyCheck(name, status, critical, "2026-08-15T12:30:00+00:00")


def evaluate(**overrides):
    values = {
        "run_id": "run-1",
        "schedule_name": "daily-alpha-0530-pst",
        "scheduled_for": "2026-08-15T12:30:00+00:00",
        "started_at": "2026-08-15T12:30:01+00:00",
        "completed_at": "2026-08-15T12:31:00+00:00",
        "data_status": DataStatus.DATA_OK,
        "input_records": 100,
        "output_records": 100,
        "rejected_records": 0,
        "dependencies": (dependency(), dependency("ORATS")),
    }
    values.update(overrides)
    return RunMonitor().evaluate(**values)


def test_clean_run_can_publish():
    result = evaluate()
    assert result.status == RunStatus.SUCCESS
    assert result.publication_allowed is True
    assert result.alerts == ()


@pytest.mark.parametrize(
    "data_status", [DataStatus.STALE_DATA, DataStatus.PARTIAL_DATA, DataStatus.DATA_ERROR]
)
def test_nonclean_data_blocks_publication(data_status):
    result = evaluate(data_status=data_status)
    assert result.status == RunStatus.FAILED
    assert result.publication_allowed is False


def test_failed_critical_dependency_blocks_partial_newsletter():
    result = evaluate(dependencies=(dependency("ORATS", DependencyStatus.FAILED),))
    assert result.status == RunStatus.FAILED
    assert result.publication_allowed is False
    assert any(alert.code == "DEPENDENCY_FAILED" for alert in result.alerts)


def test_record_mismatch_is_critical():
    result = evaluate(output_records=99)
    assert result.status == RunStatus.FAILED
    assert any(alert.severity == AlertSeverity.CRITICAL for alert in result.alerts)


def test_noncritical_degradation_is_reported_but_can_publish():
    result = evaluate(
        dependencies=(dependency(), dependency("NEWS", DependencyStatus.DEGRADED, False))
    )
    assert result.status == RunStatus.DEGRADED
    assert result.publication_allowed is True


def test_incomplete_run_blocks_publication():
    assert evaluate(completed_at=None).publication_allowed is False
