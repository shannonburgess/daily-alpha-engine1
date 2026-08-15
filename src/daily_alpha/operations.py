"""Immutable lineage, schedule monitoring, recovery, and change-ledger controls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


class PullWindow(StrEnum):
    MORNING_0530 = "MORNING_0530"
    AFTERNOON_1430 = "AFTERNOON_1430"


class RecoveryStatus(StrEnum):
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RECOVERED = "RECOVERED"
    EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True)
class ImmutableRunManifest:
    run_id: str
    input_hashes: tuple[tuple[str, str], ...]
    code_version: str
    config_version: str
    policy_version: str
    created_at: str
    prior_manifest_hash: str | None = None

    def __post_init__(self) -> None:
        if not all((self.run_id, self.code_version, self.config_version, self.policy_version)):
            raise ValueError("run and version identifiers are required")
        datetime.fromisoformat(self.created_at)
        if not self.input_hashes:
            raise ValueError("at least one archived input hash is required")
        if any(len(value) != 64 for _, value in self.input_hashes):
            raise ValueError("input hashes must be SHA-256 values")

    @property
    def manifest_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "manifest_hash": self.manifest_hash}


@dataclass(frozen=True)
class PullReceipt:
    window: PullWindow
    completed_at: str
    input_hash: str

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.completed_at)
        if len(self.input_hash) != 64:
            raise ValueError("input_hash must be SHA-256")


@dataclass(frozen=True)
class ScheduleAlert:
    code: str
    window: PullWindow
    expected_by: str
    observed_at: str


def missed_pull_alerts(
    *,
    observed_at: datetime,
    receipts: tuple[PullReceipt, ...],
    grace: timedelta = timedelta(minutes=15),
) -> tuple[ScheduleAlert, ...]:
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    local = observed_at.astimezone(PACIFIC)
    deadlines = (
        (PullWindow.MORNING_0530, time(5, 30)),
        (PullWindow.AFTERNOON_1430, time(14, 30)),
    )
    received = {
        receipt.window
        for receipt in receipts
        if datetime.fromisoformat(receipt.completed_at).astimezone(PACIFIC).date() == local.date()
    }
    alerts = []
    for window, clock in deadlines:
        deadline = datetime.combine(local.date(), clock, PACIFIC) + grace
        if local > deadline and window not in received:
            alerts.append(
                ScheduleAlert(
                    code=f"MISSED_PULL_{window.value}",
                    window=window,
                    expected_by=deadline.isoformat(),
                    observed_at=local.isoformat(),
                )
            )
    return tuple(alerts)


@dataclass(frozen=True)
class RetryPolicy:
    maximum_attempts: int = 3
    base_delay_seconds: int = 60

    def __post_init__(self) -> None:
        if self.maximum_attempts <= 0 or self.base_delay_seconds <= 0:
            raise ValueError("retry policy values must be positive")

    def delay_for(self, attempt: int) -> int:
        if attempt <= 0 or attempt > self.maximum_attempts:
            raise ValueError("attempt is outside retry policy")
        return self.base_delay_seconds * (2 ** (attempt - 1))


@dataclass(frozen=True)
class RecoveryRecord:
    run_id: str
    attempt: int
    status: RecoveryStatus
    failure_code: str
    occurred_at: str
    next_retry_seconds: int | None

    def __post_init__(self) -> None:
        if not self.run_id or not self.failure_code or self.attempt <= 0:
            raise ValueError("recovery identity is required")
        datetime.fromisoformat(self.occurred_at)


@dataclass(frozen=True)
class ChangeLedger:
    as_of: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]

    @classmethod
    def compare(
        cls, *, as_of: str, previous: tuple[str, ...], current: tuple[str, ...]
    ) -> "ChangeLedger":
        datetime.fromisoformat(as_of)
        before, after = set(previous), set(current)
        return cls(
            as_of,
            tuple(sorted(after - before)),
            tuple(sorted(before - after)),
            tuple(sorted(before & after)),
        )
