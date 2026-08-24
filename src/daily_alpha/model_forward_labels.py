"""Build prospective realized-R labels from immutable current-window market evidence.

The adapter deliberately refuses historical backfill evidence. A realized outcome becomes
model-eligible only when exact current-window market evidence for the outcome has actually
been captured after the declared horizon matured. This module derives realized R from
explicit entry/exit prices and initial per-share risk; it does not fit models or authorize
PAPER/live actions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Literal

from .model_dataset_builder import RealizedRLabelObservation
from .model_feed_observations import ImmutableFeedEvidence, validate_immutable_feed_evidence
from .model_training import ModelTrainingError

_ALLOWED_PROVIDERS = frozenset({"MASSIVE", "TIINGO"})
_SOURCE_REVISION = "prospective-realized-r-v1"


@dataclass(frozen=True, slots=True)
class ProspectiveRealizedRInputs:
    """Exact scalar inputs required to derive one realized-R research label."""

    security_id: str
    decision_at: datetime
    horizon_days: int
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    exit_price: float
    initial_risk_per_share: float
    entry_source_as_of: datetime
    exit_source_as_of: datetime

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        direction = self.direction.strip().upper()
        if not security_id:
            raise ModelTrainingError("FORWARD_LABEL_SECURITY_ID_REQUIRED")
        _require_aware(self.decision_at, "FORWARD_LABEL_DECISION_AT")
        _require_aware(self.entry_source_as_of, "FORWARD_LABEL_ENTRY_SOURCE_AS_OF")
        _require_aware(self.exit_source_as_of, "FORWARD_LABEL_EXIT_SOURCE_AS_OF")
        if self.horizon_days < 1:
            raise ModelTrainingError("FORWARD_LABEL_HORIZON_DAYS_MUST_BE_POSITIVE")
        if direction not in {"LONG", "SHORT"}:
            raise ModelTrainingError("FORWARD_LABEL_DIRECTION_INVALID")
        entry_price = _positive_finite(self.entry_price, "FORWARD_LABEL_ENTRY_PRICE")
        exit_price = _positive_finite(self.exit_price, "FORWARD_LABEL_EXIT_PRICE")
        risk = _positive_finite(
            self.initial_risk_per_share,
            "FORWARD_LABEL_INITIAL_RISK_PER_SHARE",
        )
        if self.entry_source_as_of > self.decision_at:
            raise ModelTrainingError("FORWARD_LABEL_ENTRY_SOURCE_AFTER_DECISION")
        maturity = self.decision_at + timedelta(days=self.horizon_days)
        if self.exit_source_as_of < maturity:
            raise ModelTrainingError("FORWARD_LABEL_EXIT_SOURCE_BEFORE_HORIZON_MATURITY")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "entry_price", entry_price)
        object.__setattr__(self, "exit_price", exit_price)
        object.__setattr__(self, "initial_risk_per_share", risk)

    @property
    def realized_r(self) -> float:
        pnl_per_share = (
            self.exit_price - self.entry_price
            if self.direction == "LONG"
            else self.entry_price - self.exit_price
        )
        return pnl_per_share / self.initial_risk_per_share


@dataclass(frozen=True, slots=True)
class ProspectiveRealizedRLabelPacket:
    """One deterministic research-only label plus exact entry/outcome evidence."""

    label: RealizedRLabelObservation
    inputs: ProspectiveRealizedRInputs
    entry_evidence: ImmutableFeedEvidence
    outcome_evidence: ImmutableFeedEvidence
    retuning_authorized: bool = False
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if any(
            (
                self.retuning_authorized,
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("FORWARD_LABEL_PACKET_CANNOT_AUTHORIZE_ACTION")
        if self.label.security_id != self.inputs.security_id:
            raise ModelTrainingError("FORWARD_LABEL_PACKET_SECURITY_MISMATCH")
        if self.label.decision_at != self.inputs.decision_at:
            raise ModelTrainingError("FORWARD_LABEL_PACKET_DECISION_MISMATCH")
        if self.label.horizon_days != self.inputs.horizon_days:
            raise ModelTrainingError("FORWARD_LABEL_PACKET_HORIZON_MISMATCH")

    @property
    def packet_id(self) -> str:
        return _sha(
            {
                "label_id": self.label.label_id,
                "entry_evidence_id": self.entry_evidence.evidence_id,
                "outcome_evidence_id": self.outcome_evidence.evidence_id,
                "security_id": self.inputs.security_id,
                "decision_at": self.inputs.decision_at.isoformat(),
                "horizon_days": self.inputs.horizon_days,
                "direction": self.inputs.direction,
                "entry_price": self.inputs.entry_price,
                "exit_price": self.inputs.exit_price,
                "initial_risk_per_share": self.inputs.initial_risk_per_share,
                "entry_source_as_of": self.inputs.entry_source_as_of.isoformat(),
                "exit_source_as_of": self.inputs.exit_source_as_of.isoformat(),
            }
        )


def build_prospective_realized_r_label(
    *,
    entry_raw_body: bytes,
    entry_receipt: Mapping[str, Any],
    outcome_raw_body: bytes,
    outcome_receipt: Mapping[str, Any],
    inputs: ProspectiveRealizedRInputs,
) -> ProspectiveRealizedRLabelPacket:
    """Derive one realized-R label without permitting historical knowledge backdating."""
    entry = validate_immutable_feed_evidence(raw_body=entry_raw_body, receipt=entry_receipt)
    outcome = validate_immutable_feed_evidence(
        raw_body=outcome_raw_body,
        receipt=outcome_receipt,
    )
    _require_current_market_evidence(entry, role="ENTRY")
    _require_current_market_evidence(outcome, role="OUTCOME")

    if entry.provider != outcome.provider:
        raise ModelTrainingError("FORWARD_LABEL_PROVIDER_MISMATCH")
    if entry.target != inputs.security_id or outcome.target != inputs.security_id:
        raise ModelTrainingError("FORWARD_LABEL_EVIDENCE_TARGET_MISMATCH")
    if entry.captured_at > inputs.decision_at:
        raise ModelTrainingError("FORWARD_LABEL_ENTRY_CAPTURE_AFTER_DECISION")
    if inputs.entry_source_as_of > entry.captured_at:
        raise ModelTrainingError("FORWARD_LABEL_ENTRY_SOURCE_AFTER_CAPTURE")

    maturity = inputs.decision_at + timedelta(days=inputs.horizon_days)
    if outcome.captured_at < maturity:
        raise ModelTrainingError("FORWARD_LABEL_OUTCOME_CAPTURE_BEFORE_HORIZON_MATURITY")
    if inputs.exit_source_as_of > outcome.captured_at:
        raise ModelTrainingError("FORWARD_LABEL_EXIT_SOURCE_AFTER_CAPTURE")
    if outcome.captured_at <= inputs.decision_at:
        raise ModelTrainingError("FORWARD_LABEL_OUTCOME_CAPTURE_NOT_AFTER_DECISION")

    lineage_hash = _sha(
        {
            "schema": _SOURCE_REVISION,
            "entry_source_revision": entry.source_revision,
            "outcome_source_revision": outcome.source_revision,
            "entry_source_as_of": inputs.entry_source_as_of.isoformat(),
            "exit_source_as_of": inputs.exit_source_as_of.isoformat(),
        }
    )
    label = RealizedRLabelObservation(
        security_id=inputs.security_id,
        decision_at=inputs.decision_at,
        horizon_days=inputs.horizon_days,
        realized_r=inputs.realized_r,
        known_at=outcome.captured_at,
        evidence_ids=tuple(sorted({entry.evidence_id, outcome.evidence_id})),
        source_revision=f"{_SOURCE_REVISION}:{lineage_hash}",
    )
    return ProspectiveRealizedRLabelPacket(
        label=label,
        inputs=inputs,
        entry_evidence=entry,
        outcome_evidence=outcome,
    )


def _require_current_market_evidence(evidence: ImmutableFeedEvidence, *, role: str) -> None:
    if evidence.provider not in _ALLOWED_PROVIDERS:
        raise ModelTrainingError(f"FORWARD_LABEL_{role}_PROVIDER_NOT_MARKET_DATA")
    if evidence.capture_mode != "CURRENT_WINDOW":
        raise ModelTrainingError(f"FORWARD_LABEL_{role}_MUST_USE_CURRENT_WINDOW_EVIDENCE")
    if evidence.historical_known_at_backdating_authorized:
        raise ModelTrainingError(f"FORWARD_LABEL_{role}_HISTORICAL_BACKDATING_FORBIDDEN")


def _positive_finite(value: float, field: str) -> float:
    normalized = float(value)
    if not isfinite(normalized) or normalized <= 0.0:
        raise ModelTrainingError(f"{field}_MUST_BE_POSITIVE_FINITE")
    return normalized


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelTrainingError(f"{field}_MUST_BE_TIMEZONE_AWARE")


def _sha(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ProspectiveRealizedRInputs",
    "ProspectiveRealizedRLabelPacket",
    "build_prospective_realized_r_label",
]
