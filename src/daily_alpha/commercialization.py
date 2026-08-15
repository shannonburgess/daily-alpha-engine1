"""Institutional publication records, fund controls, and commercialization gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum

RESEARCH_DISCLAIMER = (
    "Research and paper-trading output only; not investment advice. "
    "Paper and hypothetical results are not live performance."
)


class RecommendationAction(StrEnum):
    ENTER = "ENTER"
    WAIT = "WAIT"
    CANCEL = "CANCEL"
    REJECT = "REJECT"


class RecommendationState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PerformanceBasis(StrEnum):
    PAPER = "PAPER"
    HYPOTHETICAL = "HYPOTHETICAL"
    BACKTEST = "BACKTEST"


class ComplianceStatus(StrEnum):
    NOT_READY = "NOT_READY"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"


@dataclass(frozen=True)
class RecommendationRecord:
    recommendation_id: str
    decision_id: str
    as_of: str
    symbol: str
    action: RecommendationAction
    state: RecommendationState
    reason_codes: tuple[str, ...]
    instrument: str
    instrument_reason: str
    entry: float | None
    invalidation: float | None
    targets: tuple[float, ...]
    horizon: str
    planned_loss: float
    expected_reward: float
    confidence: float
    performance_basis: PerformanceBasis
    gross_pnl: float | None = None
    fees: float = 0.0
    slippage: float = 0.0

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.as_of)
        if not all(
            (
                self.recommendation_id,
                self.decision_id,
                self.symbol,
                self.reason_codes,
                self.instrument_reason,
                self.horizon,
            )
        ):
            raise ValueError("recommendation identity, reasons, and horizon are required")
        if self.instrument not in {"OPTION", "STOCK", "NO_TRADE"}:
            raise ValueError("instrument must be OPTION, STOCK, or NO_TRADE")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if min(self.planned_loss, self.expected_reward, self.fees, self.slippage) < 0:
            raise ValueError("loss, reward, fees, and slippage cannot be negative")
        if self.action == RecommendationAction.ENTER:
            if self.instrument == "NO_TRADE" or self.entry is None or self.invalidation is None:
                raise ValueError("ENTER requires an instrument, entry, and invalidation")
            if not self.targets:
                raise ValueError("ENTER requires at least one target")
        if (
            self.action in {RecommendationAction.CANCEL, RecommendationAction.REJECT}
            and self.instrument != "NO_TRADE"
        ):
            raise ValueError("cancelled or rejected records must use NO_TRADE")

    @property
    def net_pnl(self) -> float | None:
        if self.gross_pnl is None:
            return None
        return self.gross_pnl - self.fees - self.slippage


@dataclass(frozen=True)
class PublicationArchive:
    publication_id: str
    report_date: str
    generated_at: str
    canonical_run_id: str
    methodology_version: str
    records: tuple[RecommendationRecord, ...]
    changes_since_yesterday: tuple[str, ...]
    prior_archive_hash: str | None = None
    disclaimer: str = RESEARCH_DISCLAIMER

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.generated_at)
        if not all(
            (
                self.publication_id,
                self.report_date,
                self.canonical_run_id,
                self.methodology_version,
                self.disclaimer,
            )
        ):
            raise ValueError("publication identity, lineage, and disclaimer are required")
        ids = [record.recommendation_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("recommendation IDs must be unique")
        if "paper" not in self.disclaimer.lower() or "not live" not in self.disclaimer.lower():
            raise ValueError("publication must distinguish paper/hypothetical from live")

    @property
    def archive_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def performance_by_basis(self) -> dict[str, dict[str, float | int]]:
        result: dict[str, dict[str, float | int]] = {}
        for basis in PerformanceBasis:
            records = [record for record in self.records if record.performance_basis == basis]
            gross = sum(record.gross_pnl or 0.0 for record in records)
            net = sum(record.net_pnl or 0.0 for record in records)
            result[basis.value] = {"records": len(records), "gross_pnl": gross, "net_pnl": net}
        return result

    def validate_complete_history(self, canonical_ids: tuple[str, ...]) -> None:
        published = {record.recommendation_id for record in self.records}
        missing = set(canonical_ids) - published
        if missing:
            raise ValueError(f"publication omitted canonical records: {sorted(missing)}")


@dataclass(frozen=True)
class CorrectionRecord:
    correction_id: str
    publication_id: str
    recommendation_id: str
    occurred_at: str
    reason: str
    before_hash: str
    corrected_value: str
    approved_by: str

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.occurred_at)
        if not all(asdict(self).values()) or len(self.before_hash) != 64:
            raise ValueError("correction identity, reason, hash, and approver are required")


@dataclass(frozen=True)
class ValuationReconciliation:
    as_of: str
    internal_nav: float
    administrator_nav: float
    tolerance: float
    independent_price_source: str
    exceptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.as_of)
        if not self.independent_price_source or self.tolerance < 0:
            raise ValueError("independent valuation source and tolerance are required")

    @property
    def difference(self) -> float:
        return self.internal_nav - self.administrator_nav

    @property
    def reconciled(self) -> bool:
        return abs(self.difference) <= self.tolerance and not self.exceptions


@dataclass(frozen=True)
class FundRiskReport:
    as_of: str
    nav: float
    gross_exposure: float
    net_exposure: float
    var_95: float
    stress_loss: float
    liquid_days: float
    estimated_capacity: float
    drawdown: float

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.as_of)
        if self.nav <= 0 or min(self.var_95, self.stress_loss, self.liquid_days) < 0:
            raise ValueError("fund risk values are invalid")

    @property
    def gross_exposure_nav(self) -> float:
        return self.gross_exposure / self.nav

    @property
    def net_exposure_nav(self) -> float:
        return self.net_exposure / self.nav


REQUIRED_CONTROLS = frozenset(
    {
        "VALUATION_POLICY",
        "RESTRICTED_LIST",
        "PERSONAL_TRADING",
        "CONFLICTS",
        "BEST_EXECUTION",
        "BUSINESS_CONTINUITY",
        "CYBER_SECURITY",
        "VENDOR_RISK",
        "INCIDENT_RESPONSE",
        "INVESTOR_REPORTING",
        "DUE_DILIGENCE_DATA_ROOM",
        "LEGAL_REVIEW",
        "TAX_REVIEW",
        "COMPLIANCE_REVIEW",
    }
)


@dataclass(frozen=True)
class ComplianceReadiness:
    status: ComplianceStatus
    completed_controls: frozenset[str]
    approved_by: str | None = None
    approved_at: str | None = None

    @property
    def missing_controls(self) -> tuple[str, ...]:
        return tuple(sorted(REQUIRED_CONTROLS - self.completed_controls))

    @property
    def commercialization_allowed(self) -> bool:
        return (
            self.status == ComplianceStatus.APPROVED
            and not self.missing_controls
            and bool(self.approved_by)
            and bool(self.approved_at)
        )


def gate_commercialization(
    *,
    readiness: ComplianceReadiness,
    reconciliation: ValuationReconciliation,
    publication: PublicationArchive,
    canonical_ids: tuple[str, ...],
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    try:
        publication.validate_complete_history(canonical_ids)
    except ValueError:
        reasons.append("INCOMPLETE_TRACK_RECORD")
    if not reconciliation.reconciled:
        reasons.append("NAV_RECONCILIATION_FAILED")
    if not readiness.commercialization_allowed:
        reasons.append("COMPLIANCE_NOT_APPROVED")
    return not reasons, tuple(reasons or ("COMMERCIALIZATION_CONTROLS_PASSED",))
