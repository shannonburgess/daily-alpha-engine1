import pytest

from daily_alpha.provenance_manifest import (
    ProvenanceValidationError,
    ReportProvenanceManifest,
    SourceEvidence,
    build_manifest,
)


def _source(source_id: str = "OVTLYR") -> SourceEvidence:
    return SourceEvidence(
        source_id=source_id,
        source_as_of_at="2026-08-17T20:00:00-04:00",
        retrieved_at="2026-08-17T20:05:00-04:00",
        freshness_status="FRESH",
        evidence_locator=f"s3://immutable/{source_id.lower()}/2026-08-17.json",
        content_sha256="a" * 64,
        schema_version="1",
    )


def _manifest(**overrides):
    values = {
        "report_id": "daily-alpha-2026-08-17-eod",
        "report_type": "EOD_BRIEF",
        "generated_at": "2026-08-17T20:20:00-04:00",
        "source_as_of_at": "2026-08-17T20:00:00-04:00",
        "strategy_version": "v2.4",
        "model_version": "ranker-3",
        "methodology_version": "perf-1",
        "ranking_schema_version": "rank-2",
        "entitlement_tier": "RESEARCH_PLUS",
        "environment": "staging",
        "git_commit": "abc123",
        "build_id": "build-99",
        "config_hash": "cfg-123",
        "performance_basis": "PAPER",
        "benchmark_id": "SPY_TOTAL_RETURN",
        "cost_model_version": "cost-1",
        "option_mark_policy": "EXECUTABLE_SIDE_V1",
        "archive_locator": "s3://reports/2026-08-17/eod.json",
        "delivery_correlation_id": "delivery-123",
        "sources": (_source("ORATS"), _source("OVTLYR")),
    }
    values.update(overrides)
    return ReportProvenanceManifest(**values)


def test_hash_is_deterministic_even_if_source_order_changes():
    left = _manifest(sources=(_source("OVTLYR"), _source("ORATS")))
    right = _manifest(sources=(_source("ORATS"), _source("OVTLYR")))
    assert left.evidence_hash() == right.evidence_hash()
    assert left.immutable_identity() == right.immutable_identity()


def test_changed_source_evidence_changes_manifest_hash():
    base = _manifest()
    revised = _manifest(
        sources=(
            _source("ORATS"),
            SourceEvidence(
                source_id="OVTLYR",
                source_as_of_at="2026-08-17T20:00:00-04:00",
                retrieved_at="2026-08-17T20:06:00-04:00",
                freshness_status="FRESH",
                evidence_locator="s3://immutable/ovtlyr/2026-08-17.json",
                content_sha256="b" * 64,
                schema_version="1",
            ),
        )
    )
    assert base.evidence_hash() != revised.evidence_hash()


def test_footer_is_customer_safe_and_surfaces_degraded_data():
    stale = SourceEvidence(
        source_id="ORATS",
        source_as_of_at="2026-08-17T19:00:00-04:00",
        retrieved_at="2026-08-17T20:05:00-04:00",
        freshness_status="STALE",
        evidence_locator="s3://immutable/orats/2026-08-17.json",
        content_sha256="c" * 64,
    )
    footer = _manifest(sources=(stale,)).customer_safe_footer()
    assert footer["data_quality"] == "DEGRADED"
    assert footer["performance_basis"] == "PAPER"
    assert "delivery_correlation_id" not in footer
    assert "archive_locator" not in footer


def test_missing_sources_fail_closed():
    with pytest.raises(ProvenanceValidationError, match="at least one source"):
        _manifest(sources=()).validate()


def test_invalid_basis_and_freshness_are_rejected():
    with pytest.raises(ProvenanceValidationError, match="performance_basis"):
        _manifest(performance_basis="MIXED").validate()
    with pytest.raises(ProvenanceValidationError, match="freshness_status"):
        _manifest(
            sources=(
                SourceEvidence(
                    source_id="ORATS",
                    source_as_of_at="2026-08-17",
                    retrieved_at="2026-08-17",
                    freshness_status="UNKNOWN",
                    evidence_locator="evidence",
                ),
            )
        ).validate()


def test_build_manifest_validates_before_returning():
    manifest = build_manifest(
        report_id="r1",
        report_type="MORNING_BRIEF",
        generated_at="2026-08-18T08:00:00-04:00",
        source_as_of_at="2026-08-18T07:30:00-04:00",
        strategy_version="v2.4",
        model_version="ranker-3",
        methodology_version="perf-1",
        ranking_schema_version="rank-2",
        entitlement_tier="RESEARCH",
        environment="research",
        git_commit="abc123",
        build_id="build-100",
        config_hash="cfg-100",
        sources=[_source()],
    )
    assert manifest.report_id == "r1"
