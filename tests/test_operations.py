from datetime import UTC, datetime


import pytest

from daily_alpha.operations import (
    ChangeLedger,
    ImmutableRunManifest,
    PullReceipt,
    PullWindow,
    RecoveryStatus,
    RetryPolicy,
    missed_pull_alerts,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def test_manifest_is_reproducible_and_chainable():
    manifest = ImmutableRunManifest(
        "run-1",
        (("ovtlyr.csv", HASH_A), ("orats.json", HASH_B)),
        "git:abc123",
        "config:v4",
        "risk:2026-08-15-v2",
        "2026-08-15T12:31:00+00:00",
    )
    assert len(manifest.manifest_hash) == 64
    assert manifest.to_dict()["manifest_hash"] == manifest.manifest_hash


def test_morning_and_pre_three_pm_missed_pull_alerts():
    observed = datetime(2026, 8, 15, 22, 0, tzinfo=UTC)
    alerts = missed_pull_alerts(observed_at=observed, receipts=())
    assert {item.code for item in alerts} == {
        "MISSED_PULL_MORNING_0530",
        "MISSED_PULL_AFTERNOON_1430",
    }


def test_completed_windows_do_not_alert():
    receipts = (
        PullReceipt(PullWindow.MORNING_0530, "2026-08-15T12:30:00+00:00", HASH_A),
        PullReceipt(PullWindow.AFTERNOON_1430, "2026-08-15T21:30:00+00:00", HASH_B),
    )
    assert missed_pull_alerts(
        observed_at=datetime(2026, 8, 15, 22, 0, tzinfo=UTC), receipts=receipts
    ) == ()


def test_retry_policy_is_bounded_and_deterministic():
    policy = RetryPolicy(maximum_attempts=3, base_delay_seconds=60)
    assert [policy.delay_for(i) for i in (1, 2, 3)] == [60, 120, 240]
    with pytest.raises(ValueError, match="outside"):
        policy.delay_for(4)
    assert RecoveryStatus.EXHAUSTED.value == "EXHAUSTED"


def test_prior_day_change_ledger_is_deterministic():
    ledger = ChangeLedger.compare(
        as_of="2026-08-15T12:30:00+00:00",
        previous=("AAPL", "MSFT"),
        current=("AAPL", "NVDA"),
    )
    assert ledger.added == ("NVDA",)
    assert ledger.removed == ("MSFT",)
    assert ledger.unchanged == ("AAPL",)
