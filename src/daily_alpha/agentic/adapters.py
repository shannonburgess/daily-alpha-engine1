"""Adapters from existing Daily Alpha authoritative objects to canonical evidence.

These functions deliberately wrap the current deterministic source objects instead of
reimplementing their business rules. They create research/shadow evidence only and do
not alter execution, ranking, risk, or source behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..actionable_sector import ActionableSectorEvidence
from ..equity_liquidity import LiquidityDecision
from ..ovtlyr import ClassifiedRecord
from ..pine_ingress import PineIngressRecord
from .contracts import EvidenceContractError, EvidenceRecord, EvidenceStatus

OVTLYR_EVIDENCE_SOURCE = "OVTLYR_CANONICAL"
SECTOR_EVIDENCE_SOURCE = "SERVER_ACTIONABLE_SHORTLIST"
LIQUIDITY_EVIDENCE_SOURCE = "COMPANY_LIQUIDITY_CANONICAL"
PINE_EVIDENCE_SOURCE = "TRADINGVIEW_PINE_SENSOR"


def ovtlyr_to_evidence(
    record: ClassifiedRecord,
    *,
    observed_at: datetime,
    received_at: datetime,
    source_version: str,
    source_file: str | None = None,
) -> EvidenceRecord:
    """Project one existing OVTLYR classification into the canonical evidence model."""
    provenance = {
        "classifier": "daily_alpha.ovtlyr.compare_universes",
    }
    if source_file:
        provenance["source_file"] = source_file
    return EvidenceRecord(
        symbol=record.symbol,
        evidence_type="OVTLYR_STATE",
        value={
            "status": record.status.value,
            "signal": record.signal,
            "previous_signal": record.previous_signal,
            "signal_date": record.signal_date,
            "sector": record.sector,
            "industry": record.industry,
            "trend": record.trend,
            "momentum": record.momentum,
            "optionable": record.optionable,
            "reason": record.reason,
        },
        source=OVTLYR_EVIDENCE_SOURCE,
        observed_at=observed_at,
        received_at=received_at,
        source_version=source_version,
        status=EvidenceStatus.COMPLETE,
        confidence=1.0,
        provenance=provenance,
    )


def sector_to_evidence(
    evidence: ActionableSectorEvidence,
    *,
    observed_at: datetime,
    received_at: datetime,
    source_version: str = "SERVER_ACTIONABLE_SECTOR_V1",
) -> EvidenceRecord:
    """Project server-authoritative sector evidence without changing its authority."""
    return EvidenceRecord(
        symbol=evidence.symbol,
        evidence_type="SECTOR",
        value={
            "sector": evidence.sector,
            "authority": evidence.authority,
        },
        source=SECTOR_EVIDENCE_SOURCE,
        observed_at=observed_at,
        received_at=received_at,
        source_version=source_version,
        status=EvidenceStatus.COMPLETE,
        confidence=1.0,
        provenance={
            "source_file": evidence.source_file,
            "authority": evidence.authority,
        },
    )


def liquidity_to_evidence(
    decision: LiquidityDecision,
    *,
    observed_at: datetime,
    received_at: datetime,
    source_version: str = "COMPANY_LIQUIDITY_V1",
) -> EvidenceRecord:
    """Project the existing liquidity decision as data, not as a new trade decision.

    A valid negative liquidity decision remains COMPLETE evidence: the evidence is valid
    even though the security is ineligible. Source-integrity failures are mapped to
    STALE/DATA_ERROR so the supervisor cannot confuse bad evidence with a valid rejection.
    """
    status = _liquidity_status(decision)
    return EvidenceRecord(
        symbol=decision.symbol,
        evidence_type="LIQUIDITY",
        value=decision.to_dict(),
        source=LIQUIDITY_EVIDENCE_SOURCE,
        observed_at=observed_at,
        received_at=received_at,
        source_version=source_version,
        status=status,
        confidence=1.0 if status is EvidenceStatus.COMPLETE else 0.0,
        reason_code=None if status is EvidenceStatus.COMPLETE else decision.detail,
        provenance={
            "source_date": decision.source_date or "UNKNOWN",
            "authority": "daily_alpha.equity_liquidity",
        },
    )


def pine_to_evidence(record: PineIngressRecord) -> EvidenceRecord:
    """Project a validated Pine ingress record into canonical signal evidence."""
    observed_at = _parse_aware_iso(record.bar_time, "PINE_BAR_TIME")
    received_at = _parse_aware_iso(record.received_at, "PINE_RECEIVED_AT")
    return EvidenceRecord(
        symbol=record.symbol,
        evidence_type="PINE_SIGNAL",
        value={
            "signal_id": record.signal_id,
            "action": record.action,
            "strategy": record.strategy,
            "strategy_version": record.strategy_version,
            "timeframe": record.timeframe,
            "price": record.price,
            "position_fraction": record.position_fraction,
            "runner_stage": record.runner_stage,
            "model_id": record.model_id,
            "forward_test_start": record.forward_test_start,
            "replay_max_price": record.replay_max_price,
            "stock_stop_price": record.stock_stop_price,
            "entry_type": record.entry_type,
        },
        source=PINE_EVIDENCE_SOURCE,
        observed_at=observed_at,
        received_at=received_at,
        source_version=record.schema_version,
        status=EvidenceStatus.COMPLETE,
        confidence=1.0,
        provenance={
            "ingress_source": record.source,
            "signal_id": record.signal_id,
            "schema_version": record.schema_version,
        },
    )


def _liquidity_status(decision: LiquidityDecision) -> EvidenceStatus:
    reason = decision.reason.upper()
    detail = decision.detail.upper()
    if "STALE" in reason or "STALE" in detail:
        return EvidenceStatus.STALE
    error_markers = (
        "INVALID",
        "MISMATCH",
        "MISSING_OR_DUPLICATE",
        "ROWS_MISSING",
        "DATA_ERROR",
        "UNRESOLVED",
    )
    if decision.security_type.upper() == "UNKNOWN" or any(
        marker in reason or marker in detail for marker in error_markers
    ):
        return EvidenceStatus.DATA_ERROR
    return EvidenceStatus.COMPLETE


def _parse_aware_iso(value: str, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise EvidenceContractError(f"{field_name}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EvidenceContractError(f"{field_name}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceContractError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)
