# Commercial Beta Launch Evidence Gate

Status: design-only, fail-closed, no production activation.

Tracks #171 and the commercial-readiness master backlog #81.

## Purpose

Daily Alpha has separate evidence domains for research provenance, performance methodology, identity/entitlements, billing, customer delivery, data rights, security/privacy, disaster recovery, legal-review readiness and production release controls. A commercial beta must not be activated from fragmented prose status. The launch decision needs one deterministic manifest that names the exact release candidate and proves every scope-required gate is current.

This document defines a provider-neutral evidence contract and validator behavior. It does not deploy infrastructure, activate billing, send customer email, publish a website, modify TradingView, authorize capital, or enable live trading.

## Launch scopes

A manifest declares one or more scopes:

- `WEBSITE_PUBLIC`
- `EMAIL_RESEARCH`
- `AUTHENTICATED_APP`
- `PAID_BILLING`
- `PUBLIC_PERFORMANCE`
- `COMMERCIAL_BETA`

`COMMERCIAL_BETA` is a composite scope and inherits all launch-critical controls required by the enabled product surfaces.

## Gate statuses

Only these statuses are valid:

- `PASS`
- `FAIL`
- `BLOCKED`
- `NOT_APPLICABLE`
- `EXPIRED`

A launch can be `GO` only when every gate required for the requested scope is `PASS` and fresh. `NOT_APPLICABLE` is allowed only when the manifest contains an explicit rationale plus reviewer identity/role and the gate definition permits scoped exclusion.

## Manifest contract

Top-level fields:

```json
{
  "schema_version": "1.0.0",
  "manifest_id": "immutable-id",
  "candidate_commit": "git-sha",
  "candidate_build": "artifact-or-release-id",
  "requested_scopes": ["COMMERCIAL_BETA"],
  "generated_at": "RFC3339 timestamp",
  "decision": "GO|NO_GO",
  "gates": []
}
```

Each gate record must include:

```json
{
  "gate_id": "DATA_RIGHTS_001",
  "category": "DATA_RIGHTS",
  "required_for_scope": ["EMAIL_RESEARCH", "PUBLIC_PERFORMANCE"],
  "status": "PASS|FAIL|BLOCKED|NOT_APPLICABLE|EXPIRED",
  "evidence_uri": "immutable evidence reference",
  "evidence_sha256": "sha256",
  "verified_at": "RFC3339 timestamp",
  "expires_at": "RFC3339 timestamp or null",
  "reviewer_role": "role name",
  "review_reference": "external/internal review id when required",
  "depends_on": [],
  "failure_reason": null,
  "remediation_ref": null
}
```

Evidence references must be immutable/versioned. A mutable dashboard URL alone is not sufficient launch evidence.

## Required gate families

### Research provenance and reproducibility

References: #116 / draft PR #150.

Required evidence includes immutable report/research IDs, source cutoff/freshness, strategy/model/methodology version, build/config hashes, input lineage, replay result and explicit data-quality state.

### Performance basis and claim governance

References: #86 / PR #96 / #113 / draft PR #140.

Required evidence includes ACTUAL/PAPER/BACKTEST/HYPOTHETICAL separation, benchmark/version, costs, stock/ETF/options mark policy, methodology hash, no basis mixing and claim-review state. A methodology change invalidates dependent performance gates.

### Identity, tenant isolation, entitlements and billing

References: #85 / draft PR #145.

Required evidence includes authentication/session behavior, deny-by-default authorization, tenant-isolation tests, entitlement state machine, billing webhook idempotency, billing-entitlement reconciliation, support/admin override audit and privileged recent-MFA behavior where specified.

### Customer delivery and email controls

References: #87 / PR #100 / #163 / draft PR #164.

Required evidence includes recipient idempotency, preference/suppression checks immediately before send, hard-bounce/complaint behavior, replay-safe delivery ledger, synthetic retry/replay, sender-authentication readiness before public mail and a working publication-disable path.

### Security, privacy and customer-data lifecycle

References: #103 / PR #104 / #157 / draft PR #158.

Required evidence includes environment-separated secrets, tenant isolation, privileged-action audit, dependency/config verification, customer-data inventory, retention/export/deletion behavior and proof that backup restore cannot resurrect tombstoned/deleted records.

### Reliability, disaster recovery and incident response

References: #87 / PR #111.

Required evidence includes current synthetic SLO checks, dependency/data-freshness monitoring, DLQ/replay behavior, measured restore drill, RPO/RTO evidence by data class, incident-disable path and escalation ownership.

### Data/source rights

References: #159 / draft PR #160.

`RIGHTS_UNVERIFIED` is a hard `NO_GO` for any launch scope that exposes or redistributes the affected source-derived content. The manifest records the approved use scope rather than inferring rights from a vendor name or public terms.

### Terms, privacy, disclosures, support and external review

Reference: #97.

The gate stores evidence that required launch-scope documents/checklists exist and the applicable external legal/compliance review reference is recorded. The repository does not determine legal sufficiency or claim registration/exemption/compliance.

### Production release and rollback

References: #168 and related release-control work.

Required evidence includes environment separation, immutable build/release candidate, staging rehearsal, known-good rollback artifact, drift status, rollback verification and proof the commercial research environment has no live-broker execution dependency.

### Product/support/analytics readiness

References: #88 / PR #101 / #107 / PR #108.

Required evidence includes tier promise/exclusion mapping, onboarding path, cancellation/reactivation, support owner/escalation, feedback loop, privacy-minimized analytics and customer-safe rollback/incident communication ownership.

## Mandatory fail-closed conditions

The validator must return `NO_GO` when any of the following is true for the requested scope:

- required gate missing;
- gate is `FAIL`, `BLOCKED` or `EXPIRED`;
- `RIGHTS_UNVERIFIED` affects customer-visible output;
- required external-review reference is absent;
- security/DR evidence is stale;
- performance basis or methodology conflicts with the candidate output;
- entitlement isolation or billing reconciliation fails;
- email suppression/complaint controls fail;
- provenance/replay cannot reproduce the customer-visible artifact;
- source commit/build does not match the candidate under review;
- production drift is unresolved;
- rollback artifact or publication-disable control is unavailable.

## Evidence freshness and invalidation

A gate definition declares either a fixed expiry or an invalidation trigger. Examples:

- security dependency/config evidence: expires on policy cadence or relevant dependency/config change;
- restore drill: expires on RPO/RTO cadence or material storage/schema change;
- performance methodology: invalidated by methodology, benchmark, option-mark or cost-rule change;
- data rights: invalidated by launch scope, vendor agreement/source or customer-visible output change;
- legal/compliance review: invalidated by feature/scope/claim changes identified in #97;
- entitlement tests: invalidated by authentication/session/role/subscription state-machine change;
- release rehearsal: valid only for the identified release candidate/build.

## Synthetic validator test matrix

Required tests before any release-pipeline integration:

1. all required gates PASS and fresh -> `GO`;
2. missing gate -> `NO_GO`;
3. expired gate -> `NO_GO`;
4. rights unverified -> `NO_GO`;
5. required external review absent -> `NO_GO`;
6. stale restore/security evidence -> `NO_GO`;
7. cross-tenant/entitlement failure -> `NO_GO`;
8. billing-entitlement mismatch -> `NO_GO`;
9. suppression/bounce failure -> `NO_GO`;
10. performance basis conflict -> `NO_GO`;
11. provenance replay mismatch -> `NO_GO`;
12. candidate commit/build mismatch -> `NO_GO`;
13. NOT_APPLICABLE without rationale/reviewer -> `NO_GO`;
14. unrelated optional gate failure outside requested scope -> decision follows the dependency matrix, never an implicit bypass.

## Staging rehearsal

A future approved implementation should generate the manifest against synthetic staging customers and non-production credentials only. The rehearsal proves validation and evidence resolution; it has no deploy, billing, email-send, public-publish, TradingView or trading capability.

## Explicit approval boundary

Even a valid `GO` manifest is evidence readiness, not authorization. First production activation, paid billing, public website publication, external customer email, customer onboarding, material strategy promotion, TradingView mutation and any live-trading capability remain separate explicit user-approval actions.