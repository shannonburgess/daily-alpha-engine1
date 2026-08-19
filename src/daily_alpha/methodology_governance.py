"""Commercial-beta methodology release and version-governance controls.

This module is intentionally disconnected from trading execution. It models the
customer/research release lifecycle for a methodology version and fails closed
when release evidence or version identity is incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class MethodologyState(StrEnum):
    DRAFT_RESEARCH = "DRAFT_RESEARCH"
    VALIDATING = "VALIDATING"
    APPROVED_FOR_FUTURE_RELEASE = "APPROVED_FOR_FUTURE_RELEASE"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    ROLLED_BACK = "ROLLED_BACK"


class MaterialChangeClass(StrEnum):
    PRESENTATION_ONLY = "PRESENTATION_ONLY"
    DATA_SOURCE_OR_PARSER = "DATA_SOURCE_OR_PARSER"
    RANKING_OR_FEATURE = "RANKING_OR_FEATURE"
    ENTRY_EXIT_RULE = "ENTRY_EXIT_RULE"
    PORTFOLIO_RISK_OR_SIZING = "PORTFOLIO_RISK_OR_SIZING"
    INSTRUMENT_EXPRESSION = "INSTRUMENT_EXPRESSION"
    PERFORMANCE_METHOD = "PERFORMANCE_METHOD"
    EMERGENCY_ROLLBACK = "EMERGENCY_ROLLBACK"


@dataclass(frozen=True)
class MethodologyVersion:
    methodology_id: str
    version: str
    source_commit: str
    parameter_hash: str
    data_contract_version: str
    performance_methodology_id: str
    change_class: MaterialChangeClass
    state: MethodologyState = MethodologyState.DRAFT_RESEARCH
    predecessor_id: str | None = None
    effective_from: str | None = None
    release_manifest_id: str | None = None

    def validate_identity(self) -> None:
        required = {
            "methodology_id": self.methodology_id,
            "version": self.version,
            "source_commit": self.source_commit,
            "parameter_hash": self.parameter_hash,
            "data_contract_version": self.data_contract_version,
            "performance_methodology_id": self.performance_methodology_id,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"METHOD_IDENTITY_INCOMPLETE:{','.join(sorted(missing))}")
        if self.state == MethodologyState.ACTIVE:
            if not self.effective_from:
                raise ValueError("ACTIVE_METHODOLOGY_REQUIRES_EFFECTIVE_FROM")
            if not self.release_manifest_id:
                raise ValueError("ACTIVE_METHODOLOGY_REQUIRES_RELEASE_MANIFEST")


@dataclass(frozen=True)
class MethodologyTransitionEvidence:
    event_id: str
    transitioned_at: str
    validation_evidence_ids: tuple[str, ...] = ()
    release_manifest_id: str | None = None
    explicit_release_approval: bool = False
    reason: str = ""

    def validate(self) -> None:
        if not self.event_id.strip() or not self.transitioned_at.strip():
            raise ValueError("METHODOLOGY_TRANSITION_EVIDENCE_INCOMPLETE")


_ALLOWED_TRANSITIONS: dict[MethodologyState, frozenset[MethodologyState]] = {
    MethodologyState.DRAFT_RESEARCH: frozenset({MethodologyState.VALIDATING}),
    MethodologyState.VALIDATING: frozenset(
        {MethodologyState.APPROVED_FOR_FUTURE_RELEASE, MethodologyState.RETIRED}
    ),
    MethodologyState.APPROVED_FOR_FUTURE_RELEASE: frozenset(
        {MethodologyState.ACTIVE, MethodologyState.RETIRED}
    ),
    MethodologyState.ACTIVE: frozenset(
        {MethodologyState.DEPRECATED, MethodologyState.ROLLED_BACK}
    ),
    MethodologyState.DEPRECATED: frozenset({MethodologyState.RETIRED}),
    MethodologyState.ROLLED_BACK: frozenset({MethodologyState.RETIRED}),
    MethodologyState.RETIRED: frozenset(),
}


def transition_methodology(
    methodology: MethodologyVersion,
    target: MethodologyState,
    evidence: MethodologyTransitionEvidence,
) -> MethodologyVersion:
    """Return a new immutable methodology state after fail-closed validation."""

    methodology.validate_identity()
    evidence.validate()
    if target not in _ALLOWED_TRANSITIONS[methodology.state]:
        raise ValueError(
            f"METHODOLOGY_TRANSITION_NOT_ALLOWED:{methodology.state.value}->{target.value}"
        )

    if target == MethodologyState.APPROVED_FOR_FUTURE_RELEASE:
        if not evidence.validation_evidence_ids:
            raise ValueError("METHODOLOGY_VALIDATION_EVIDENCE_REQUIRED")

    if target == MethodologyState.ACTIVE:
        if not evidence.validation_evidence_ids:
            raise ValueError("METHODOLOGY_VALIDATION_EVIDENCE_REQUIRED")
        if not evidence.release_manifest_id:
            raise ValueError("METHODOLOGY_RELEASE_MANIFEST_REQUIRED")
        if not evidence.explicit_release_approval:
            raise ValueError("METHODOLOGY_EXPLICIT_RELEASE_APPROVAL_REQUIRED")
        return replace(
            methodology,
            state=target,
            effective_from=evidence.transitioned_at,
            release_manifest_id=evidence.release_manifest_id,
        )

    return replace(methodology, state=target)


def customer_report_methodology_gate(
    *,
    report_methodology_id: str | None,
    methodology: MethodologyVersion | None,
) -> tuple[bool, str]:
    """Fail closed unless a report resolves to the exact active methodology."""

    if methodology is None or not report_methodology_id:
        return False, "METHODOLOGY_IDENTITY_MISSING"
    try:
        methodology.validate_identity()
    except ValueError:
        return False, "METHODOLOGY_IDENTITY_INVALID"
    if methodology.state != MethodologyState.ACTIVE:
        return False, "METHODOLOGY_NOT_ACTIVE"
    if report_methodology_id != methodology.methodology_id:
        return False, "METHODOLOGY_VERSION_MISMATCH"
    return True, "METHODOLOGY_VERSION_CURRENT"


def performance_eras_may_be_combined(
    methodology_ids: tuple[str, ...],
    *,
    explicit_chaining_policy: bool,
) -> tuple[bool, str]:
    """Require an explicit policy before combining materially different eras."""

    unique = {value.strip() for value in methodology_ids if value and value.strip()}
    if not unique:
        return False, "METHODOLOGY_IDENTITY_MISSING"
    if len(unique) == 1:
        return True, "SINGLE_METHODOLOGY_ERA"
    if not explicit_chaining_policy:
        return False, "MULTI_ERA_CHAINING_POLICY_REQUIRED"
    return True, "MULTI_ERA_CHAINING_POLICY_DECLARED"
