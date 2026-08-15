"""Immutable strategy-version governance and paper-release controls."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class VersionStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PAPER_APPROVED = "PAPER_APPROVED"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class StrategyVersion:
    version_id: str
    strategy_name: str
    rule_hash: str
    created_at: str
    status: VersionStatus = VersionStatus.DRAFT
    validation_report_id: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    parent_version_id: str | None = None
    change_summary: str = ""

    def __post_init__(self) -> None:
        if not all(
            (self.version_id, self.strategy_name, self.rule_hash, self.created_at)
        ):
            raise ValueError(
                "version identity, rule hash, and creation time are required"
            )
        if len(self.rule_hash) != 64:
            raise ValueError("rule_hash must be a SHA-256 hex digest")
        try:
            int(self.rule_hash, 16)
        except ValueError as exc:
            raise ValueError("rule_hash must be a SHA-256 hex digest") from exc


@dataclass(frozen=True)
class GovernanceEvent:
    event_id: str
    version_id: str
    previous_status: VersionStatus
    new_status: VersionStatus
    occurred_at: str
    actor: str
    reason: str


@dataclass(frozen=True)
class GovernedVersion:
    version: StrategyVersion
    events: tuple[GovernanceEvent, ...] = ()

    @property
    def paper_eligible(self) -> bool:
        return self.version.status == VersionStatus.PAPER_APPROVED


class StrategyGovernance:
    def record_validation(
        self,
        governed: GovernedVersion,
        *,
        validation_report_id: str,
        eligible_for_paper: bool,
        occurred_at: str,
        actor: str = "VALIDATION_ENGINE",
    ) -> GovernedVersion:
        if governed.version.status != VersionStatus.DRAFT:
            raise ValueError("only a draft version can record validation")
        if not validation_report_id:
            raise ValueError("validation_report_id is required")
        if not eligible_for_paper:
            raise ValueError("failed validation cannot advance version status")
        updated = replace(
            governed.version,
            status=VersionStatus.VALIDATED,
            validation_report_id=validation_report_id,
        )
        return self._transition(
            governed, updated, occurred_at, actor, "VALIDATION_PASSED"
        )

    def approve_for_paper(
        self,
        governed: GovernedVersion,
        *,
        approved_by: str,
        approved_at: str,
    ) -> GovernedVersion:
        if governed.version.status != VersionStatus.VALIDATED:
            raise ValueError("paper approval requires validated status")
        if not approved_by:
            raise ValueError("named approver is required")
        updated = replace(
            governed.version,
            status=VersionStatus.PAPER_APPROVED,
            approved_by=approved_by,
            approved_at=approved_at,
        )
        return self._transition(
            governed, updated, approved_at, approved_by, "PAPER_RELEASE_APPROVED"
        )

    def retire(
        self,
        governed: GovernedVersion,
        *,
        actor: str,
        occurred_at: str,
        reason: str,
    ) -> GovernedVersion:
        if governed.version.status == VersionStatus.RETIRED:
            raise ValueError("version is already retired")
        if not reason:
            raise ValueError("retirement reason is required")
        updated = replace(governed.version, status=VersionStatus.RETIRED)
        return self._transition(governed, updated, occurred_at, actor, reason)

    @staticmethod
    def _transition(
        governed: GovernedVersion,
        updated: StrategyVersion,
        occurred_at: str,
        actor: str,
        reason: str,
    ) -> GovernedVersion:
        if not occurred_at or not actor:
            raise ValueError("transition time and actor are required")
        sequence = len(governed.events) + 1
        event = GovernanceEvent(
            event_id=f"{updated.version_id}:{sequence}",
            version_id=updated.version_id,
            previous_status=governed.version.status,
            new_status=updated.status,
            occurred_at=occurred_at,
            actor=actor,
            reason=reason,
        )
        return GovernedVersion(updated, (*governed.events, event))
