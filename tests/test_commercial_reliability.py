import pytest

from daily_alpha.commercial_reliability import (
    DeliveryKind,
    DeliveryObjective,
    DeliveryObservation,
    DeliveryStatus,
    commercial_delivery_ready,
    evaluate_delivery,
)


def objective(kind=DeliveryKind.PREMARKET_NOTE):
    return DeliveryObjective(
        kind=kind,
        max_lateness_minutes=10,
        max_source_age_minutes=30,
    )


def observation(
    *,
    kind=DeliveryKind.PREMARKET_NOTE,
    delivered_at="2026-08-17T05:47:00-07:00",
    source_as_of="2026-08-17T05:30:00-07:00",
    duplicate_deliveries=0,
):
    return DeliveryObservation(
        delivery_id="delivery-1",
        kind=kind,
        scheduled_for="2026-08-17T05:45:00-07:00",
        delivered_at=delivered_at,
        source_as_of=source_as_of,
        correlation_id="corr-1",
        duplicate_deliveries=duplicate_deliveries,
    )


def test_on_time_fresh_delivery_passes():
    result = evaluate_delivery(objective=objective(), observation=observation())

    assert result.status == DeliveryStatus.PASS
    assert result.customer_safe is True
    assert result.lateness_minutes == pytest.approx(2.0)
    assert result.source_age_minutes == pytest.approx(17.0)
    assert result.reasons == ("DELIVERY_SLO_PASSED",)


def test_missing_delivery_fails_closed():
    result = evaluate_delivery(
        objective=objective(),
        observation=observation(delivered_at=None),
    )

    assert result.status == DeliveryStatus.FAIL
    assert result.customer_safe is False
    assert "DELIVERY_MISSING" in result.reasons


def test_late_or_stale_delivery_is_not_customer_safe():
    late = evaluate_delivery(
        objective=objective(),
        observation=observation(delivered_at="2026-08-17T06:10:00-07:00"),
    )
    stale = evaluate_delivery(
        objective=objective(),
        observation=observation(source_as_of="2026-08-17T04:00:00-07:00"),
    )

    assert "DELIVERY_LATE" in late.reasons
    assert "SOURCE_STALE" in stale.reasons
    assert late.customer_safe is False
    assert stale.customer_safe is False


def test_duplicate_delivery_is_detected():
    result = evaluate_delivery(
        objective=objective(),
        observation=observation(duplicate_deliveries=1),
    )

    assert result.status == DeliveryStatus.FAIL
    assert result.reasons == ("DUPLICATE_DELIVERY",)


def test_objective_and_observation_kinds_must_match():
    with pytest.raises(ValueError, match="kinds must match"):
        evaluate_delivery(
            objective=objective(DeliveryKind.EOD_BRIEF),
            observation=observation(DeliveryKind.PREMARKET_NOTE),
        )


def test_commercial_delivery_ready_requires_nonempty_all_pass():
    passing = evaluate_delivery(objective=objective(), observation=observation())
    failing = evaluate_delivery(
        objective=objective(),
        observation=observation(delivered_at=None),
    )

    assert commercial_delivery_ready(()) is False
    assert commercial_delivery_ready((passing,)) is True
    assert commercial_delivery_ready((passing, failing)) is False
