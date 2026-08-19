import pytest

from daily_alpha.methodology_governance import (
    MaterialChangeClass,
    MethodologyState,
    MethodologyTransitionEvidence,
    MethodologyVersion,
    customer_report_methodology_gate,
    performance_eras_may_be_combined,
    transition_methodology,
)


def methodology(state=MethodologyState.DRAFT_RESEARCH):
    return MethodologyVersion(
        methodology_id="daily-alpha-v2.4",
        version="2.4",
        source_commit="abc123",
        parameter_hash="params-123",
        data_contract_version="ovtlyr-orats-v1",
        performance_methodology_id="perf-v1",
        change_class=MaterialChangeClass.ENTRY_EXIT_RULE,
        state=state,
        effective_from=("2026-08-19T15:00:00+00:00" if state == MethodologyState.ACTIVE else None),
        release_manifest_id=("release-1" if state == MethodologyState.ACTIVE else None),
    )


def evidence(**kwargs):
    values = {
        "event_id": "event-1",
        "transitioned_at": "2026-08-19T15:00:00+00:00",
    }
    values.update(kwargs)
    return MethodologyTransitionEvidence(**values)


def test_release_lifecycle_requires_validation_and_explicit_release_approval():
    validating = transition_methodology(
        methodology(), MethodologyState.VALIDATING, evidence()
    )
    with pytest.raises(ValueError, match="VALIDATION_EVIDENCE_REQUIRED"):
        transition_methodology(
            validating, MethodologyState.APPROVED_FOR_FUTURE_RELEASE, evidence()
        )

    approved = transition_methodology(
        validating,
        MethodologyState.APPROVED_FOR_FUTURE_RELEASE,
        evidence(validation_evidence_ids=("walk-forward-1",)),
    )
    with pytest.raises(ValueError, match="RELEASE_MANIFEST_REQUIRED"):
        transition_methodology(
            approved,
            MethodologyState.ACTIVE,
            evidence(
                validation_evidence_ids=("walk-forward-1",),
                explicit_release_approval=True,
            ),
        )
    with pytest.raises(ValueError, match="EXPLICIT_RELEASE_APPROVAL_REQUIRED"):
        transition_methodology(
            approved,
            MethodologyState.ACTIVE,
            evidence(
                validation_evidence_ids=("walk-forward-1",),
                release_manifest_id="release-1",
            ),
        )

    active = transition_methodology(
        approved,
        MethodologyState.ACTIVE,
        evidence(
            validation_evidence_ids=("walk-forward-1",),
            release_manifest_id="release-1",
            explicit_release_approval=True,
        ),
    )
    assert active.state == MethodologyState.ACTIVE
    assert active.release_manifest_id == "release-1"
    assert active.effective_from == "2026-08-19T15:00:00+00:00"


def test_retired_or_rolled_back_methodology_cannot_silently_reactivate():
    rolled_back = MethodologyVersion(
        **{
            **methodology(MethodologyState.ACTIVE).__dict__,
            "state": MethodologyState.ROLLED_BACK,
        }
    )
    with pytest.raises(ValueError, match="TRANSITION_NOT_ALLOWED"):
        transition_methodology(
            rolled_back,
            MethodologyState.ACTIVE,
            evidence(
                validation_evidence_ids=("walk-forward-1",),
                release_manifest_id="release-2",
                explicit_release_approval=True,
            ),
        )


def test_customer_report_gate_requires_exact_active_methodology_identity():
    active = methodology(MethodologyState.ACTIVE)
    assert customer_report_methodology_gate(
        report_methodology_id=active.methodology_id, methodology=active
    ) == (True, "METHODOLOGY_VERSION_CURRENT")
    assert customer_report_methodology_gate(
        report_methodology_id="daily-alpha-v2.5", methodology=active
    ) == (False, "METHODOLOGY_VERSION_MISMATCH")
    assert customer_report_methodology_gate(
        report_methodology_id=active.methodology_id,
        methodology=MethodologyVersion(
            **{**active.__dict__, "state": MethodologyState.DEPRECATED}
        ),
    ) == (False, "METHODOLOGY_NOT_ACTIVE")


def test_multi_era_performance_requires_explicit_chaining_policy():
    assert performance_eras_may_be_combined(
        ("daily-alpha-v2.4", "daily-alpha-v2.4"),
        explicit_chaining_policy=False,
    ) == (True, "SINGLE_METHODOLOGY_ERA")
    assert performance_eras_may_be_combined(
        ("daily-alpha-v2.4", "daily-alpha-v2.5"),
        explicit_chaining_policy=False,
    ) == (False, "MULTI_ERA_CHAINING_POLICY_REQUIRED")
    assert performance_eras_may_be_combined(
        ("daily-alpha-v2.4", "daily-alpha-v2.5"),
        explicit_chaining_policy=True,
    ) == (True, "MULTI_ERA_CHAINING_POLICY_DECLARED")
