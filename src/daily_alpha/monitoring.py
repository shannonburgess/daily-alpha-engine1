"""Operational monitoring and fail-closed publication controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .data_quality import DataStatus


class DependencyStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    MISSING = "MISSING"


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    status: DependencyStatus
    critical: bool
    observed_at: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.observed_at:
            raise ValueError("dependency name and observed_at are required")


@dataclass(frozen=True)
class OperationalAlert:
    code: str
    severity: AlertSeverity
    message: str


@dataclass(frozen=True)
class OperationalHealth:
    run_id: str
    schedule_name: str
    scheduled_for: str
    started_at: str
    completed_at: str | None
    data_status: DataStatus
    input_records: int
    output_records: int
    rejected_records: int
    dependencies: tuple[DependencyCheck, ...]
    status: RunStatus
    publication_allowed: bool
    alerts: tuple[OperationalAlert, ...]


class RunMonitor:
    def evaluate(
        self,
        *,
        run_id: str,
        schedule_name: str,
        scheduled_for: str,
        started_at: str,
        completed_at: str | None,
        data_status: DataStatus,
        input_records: int,
        output_records: int,
        rejected_records: int,
        dependencies: tuple[DependencyCheck, ...],
    ) -> OperationalHealth:
        if not all((run_id, schedule_name, scheduled_for, started_at)):
            raise ValueError("run identity and schedule fields are required")
        if min(input_records, output_records, rejected_records) < 0:
            raise ValueError("record counts cannot be negative")

        alerts: list[OperationalAlert] = []
        critical_failures = [
            item
            for item in dependencies
            if item.critical and item.status != DependencyStatus.HEALTHY
        ]
        degraded = [item for item in dependencies if item.status == DependencyStatus.DEGRADED]

        if completed_at is None:
            alerts.append(self._alert("RUN_INCOMPLETE", AlertSeverity.CRITICAL))
        if data_status != DataStatus.DATA_OK:
            alerts.append(self._alert(f"DATA_{data_status.value}", AlertSeverity.CRITICAL))
        for item in critical_failures:
            alerts.append(
                OperationalAlert(
                    f"DEPENDENCY_{item.status.value}",
                    AlertSeverity.CRITICAL,
                    f"Critical dependency {item.name} is {item.status.value}.",
                )
            )
        if input_records != output_records + rejected_records:
            alerts.append(self._alert("RECORD_COUNT_MISMATCH", AlertSeverity.CRITICAL))
        for item in degraded:
            if item not in critical_failures:
                alerts.append(
                    OperationalAlert(
                        "DEPENDENCY_DEGRADED",
                        AlertSeverity.WARNING,
                        f"Noncritical dependency {item.name} is degraded.",
                    )
                )

        blocked = any(alert.severity == AlertSeverity.CRITICAL for alert in alerts)
        if blocked:
            status = RunStatus.FAILED
        elif alerts or rejected_records:
            status = RunStatus.DEGRADED
            if rejected_records:
                alerts.append(self._alert("RECORDS_REJECTED", AlertSeverity.WARNING))
        else:
            status = RunStatus.SUCCESS
        return OperationalHealth(
            run_id,
            schedule_name,
            scheduled_for,
            started_at,
            completed_at,
            data_status,
            input_records,
            output_records,
            rejected_records,
            dependencies,
            status,
            publication_allowed=status != RunStatus.FAILED,
            alerts=tuple(alerts),
        )

    @staticmethod
    def _alert(code: str, severity: AlertSeverity) -> OperationalAlert:
        messages = {
            "RUN_INCOMPLETE": "Scheduled run did not complete.",
            "RECORD_COUNT_MISMATCH": "Input records do not reconcile to output and rejects.",
            "RECORDS_REJECTED": "One or more input records were rejected.",
        }
        return OperationalAlert(code, severity, messages.get(code, code.replace("_", " ")))
