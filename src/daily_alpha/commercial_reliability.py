"""Commercial-beta delivery SLO evaluation and fail-closed readiness controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DeliveryKind(StrEnum):
    PREMARKET_NOTE = "PREMARKET_NOTE"
    EOD_BRIEF = "EOD_BRIEF"
    REPORT_ARCHIVE = "REPORT_ARCHIVE"
    ENTITLEMENT_ACCESS = "ENTITLEMENT_ACCESS"


class DeliveryStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class DeliveryObjective:
    kind: DeliveryKind
    max_lateness_minutes: int
    max_source_age_minutes: int
    duplicate_tolerance: int = 0

    def __post_init__(self) -> None:
        if min(
            self.max_lateness_minutes,
            self.max_source_age_minutes,
            self.duplicate_tolerance,
        ) < 0:
            raise ValueError("delivery objective tolerances cannot be negative")


@dataclass(frozen=True)
class DeliveryObservation:
    delivery_id: str
    kind: DeliveryKind
    scheduled_for: str
    delivered_at: str | None
    source_as_of: str | None
    correlation_id: str
    duplicate_deliveries: int = 0

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.scheduled_for)
        if self.delivered_at is not None:
            datetime.fromisoformat(self.delivered_at)
        if self.source_as_of is not None:
            datetime.fromisoformat(self.source_as_of)
        if not all((self.delivery_id, self.correlation_id)):
            raise ValueError("delivery_id and correlation_id are required")
        if self.duplicate_deliveries < 0:
            raise ValueError("duplicate_deliveries cannot be negative")


@dataclass(frozen=True)
class DeliveryEvaluation:
    delivery_id: str
    status: DeliveryStatus
    customer_safe: bool
    lateness_minutes: float | None
    source_age_minutes: float | None
    reasons: tuple[str, ...]


def evaluate_delivery(
    *,
    objective: DeliveryObjective,
    observation: DeliveryObservation,
) -> DeliveryEvaluation:
    """Evaluate whether one customer-visible delivery met its configured SLO.

    The function is fail closed: missing delivery time or source timestamp blocks
    customer-safe status instead of converting incomplete evidence into success.
    """

    if objective.kind != observation.kind:
        raise ValueError("delivery objective and observation kinds must match")

    scheduled = datetime.fromisoformat(observation.scheduled_for)
    reasons: list[str] = []
    lateness: float | None = None
    source_age: float | None = None

    if observation.delivered_at is None:
        reasons.append("DELIVERY_MISSING")
    else:
        delivered = datetime.fromisoformat(observation.delivered_at)
        lateness = max(0.0, (delivered - scheduled).total_seconds() / 60)
        if lateness > objective.max_lateness_minutes:
            reasons.append("DELIVERY_LATE")

    if observation.source_as_of is None:
        reasons.append("SOURCE_TIMESTAMP_MISSING")
    else:
        source = datetime.fromisoformat(observation.source_as_of)
        reference = (
            datetime.fromisoformat(observation.delivered_at)
            if observation.delivered_at is not None
            else scheduled
        )
        source_age = max(0.0, (reference - source).total_seconds() / 60)
        if source_age > objective.max_source_age_minutes:
            reasons.append("SOURCE_STALE")

    if observation.duplicate_deliveries > objective.duplicate_tolerance:
        reasons.append("DUPLICATE_DELIVERY")

    status = DeliveryStatus.FAIL if reasons else DeliveryStatus.PASS
    return DeliveryEvaluation(
        delivery_id=observation.delivery_id,
        status=status,
        customer_safe=status == DeliveryStatus.PASS,
        lateness_minutes=lateness,
        source_age_minutes=source_age,
        reasons=tuple(reasons or ("DELIVERY_SLO_PASSED",)),
    )


def commercial_delivery_ready(evaluations: tuple[DeliveryEvaluation, ...]) -> bool:
    """Require explicit successful evidence for every supplied critical delivery."""

    return bool(evaluations) and all(item.customer_safe for item in evaluations)
