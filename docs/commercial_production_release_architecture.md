# Daily Alpha commercial production release architecture

Status: **planning / staging design only**. This document does not authorize AWS production deployment, customer launch, payment activation, public publishing, TradingView mutation, brokerage execution, or live trading.

Tracks issue #168 and the commercial-beta master backlog #81.

## Purpose

Define a provider-neutral, AWS-compatible control plane for promoting a future Daily Alpha research product from research to staging to production while keeping customer data, secrets, publication, billing, and trading boundaries explicit and auditable.

## Environment model

The system recognizes three distinct environments:

| Environment | Allowed data | Allowed delivery | Allowed billing | Allowed trading |
|---|---|---|---|---|
| research | research/public/licensed data per rights state | internal artifacts only | none | none |
| staging | synthetic customer/account data only | synthetic/test destinations only | provider sandbox/test events only | paper/research paths only where separately approved |
| production | approved customer data only after launch gates | approved customer surfaces | production billing only after explicit activation approval | **live brokerage execution prohibited** |

Environment boundaries must not rely only on naming conventions. Each environment needs separately scoped identities, secrets, encryption keys, storage prefixes/accounts, callback URLs, delivery credentials, and monitoring context. Production must never consume a staging secret by fallback.

## Release manifest

Every candidate release should produce one immutable manifest before promotion. Suggested schema:

```json
{
  "release_id": "daily-alpha-<timestamp>-<short_sha>",
  "source_commit": "<full git sha>",
  "build_artifact_hash": "sha256:<digest>",
  "environment": "staging|production",
  "strategy_versions": ["research-output-version-only"],
  "performance_methodology_version": "<version-or-none>",
  "provenance_schema_version": "<version>",
  "config_version": "<hash>",
  "required_evidence": [
    "ci",
    "security",
    "entitlement",
    "delivery",
    "backup_restore",
    "publication_kill",
    "rollback"
  ],
  "rollback_release_id": "<known-good-release>",
  "approved_for_promotion": false
}
```

The manifest contains references/hashes, never secret values.

## Required promotion evidence

A staging candidate is not production-eligible unless the applicable evidence exists and is current:

1. unit/integration/static checks are green;
2. artifact hash matches the artifact rehearsed in staging;
3. authentication/session and server-side entitlement isolation tests pass;
4. billing-event idempotency/reconciliation tests pass using synthetic/test events;
5. customer-output provenance/replay tests pass;
6. performance basis/methodology gates pass for any output that contains performance evidence;
7. report/email delivery idempotency, preferences and suppression tests pass;
8. backup/restore drill is within its evidence-validity window;
9. publication-disable/kill control has a recent successful rehearsal;
10. no unresolved environment drift is present;
11. source/data rights required by the exact customer-visible output are not `RIGHTS_UNVERIFIED`;
12. applicable external-review references required by #97 are recorded;
13. rollback target and rollback validation steps are known before promotion;
14. live trading remains disabled and absent from the commercial release path.

Missing evidence is a **NO-GO**, not a warning that can be silently ignored.

## Configuration and secrets

Configuration and secrets are different artifacts.

### Versioned configuration

Safe-to-version examples:
- feature flags that do not expose credentials;
- report schedules;
- entitlement-product mapping identifiers;
- public callback path names;
- retention-policy identifiers;
- methodology/provenance schema versions;
- release-gate thresholds.

### Secrets

Secrets must remain environment-scoped and independently revocable:
- ORATS/vendor credentials;
- billing webhook secrets/API credentials;
- customer-email provider credentials;
- authentication/session signing secrets;
- encryption/KMS key references;
- database credentials;
- any future production-only API secret.

A release must fail closed if a required secret is unavailable. It must not search another environment for a usable secret.

## Drift control

The future production environment should have an auditable desired-state inventory. Before release:

- compare observed deployable resources/configuration with the approved desired state;
- classify drift as expected/versioned or unexpected;
- block promotion on unexpected drift affecting identity, network exposure, storage, encryption, scheduled jobs, delivery, secrets, backup or publication controls;
- record the drift check in the release evidence bundle.

Console changes may be used only for emergency response if separately authorized; the resulting state must be reconciled back into canonical configuration/IaC before the next normal release.

## Rollback model

Application rollback and customer-data restore are intentionally separate.

### Application rollback

- retain the prior known-good artifact and release manifest;
- roll application/config back without rolling customer records backward;
- re-run health, entitlement, delivery and publication-disable checks after rollback.

### Data/schema recovery

- migrations should be backward-compatible where practical;
- destructive migrations require a tested restore/reconciliation plan;
- customer deletion tombstones and email suppressions must survive restore;
- rollback must not resurrect canceled entitlements, deleted accounts or suppressed destinations.

## Publication kill path

Commercial publication must be disableable independently of strategy research and independently of trading execution. The kill path should be able to stop:

- scheduled newsletters/reports;
- customer dashboard publication;
- optional research emails;
- public/sample output generation;

without deleting evidence or customer state. A kill action must be logged with release/build context and incident correlation ID.

## Observability requirements

Every production log/metric/event should carry enough non-secret context to answer which release produced it:

- environment;
- release ID;
- source/build SHA;
- component/function;
- correlation/request/delivery ID where applicable;
- error/failure class;
- source-data freshness state for research outputs.

Minimum operational signals:
- service/function errors;
- scheduled-job success/latency;
- source freshness and dependency failures;
- report generation and delivery SLO observations;
- entitlement denials/reconciliation failures;
- webhook replay/signature failures;
- backup/restore evidence age;
- publication kill state;
- environment drift state.

Customer content, access tokens, payment details and raw vendor payloads should not be copied into logs merely for debugging.

## Staging rehearsal

Before the first production activation, staging should rehearse the full release lifecycle with synthetic data:

1. build immutable artifact and release manifest;
2. deploy/reconcile staging desired state;
3. run synthetic authentication/entitlement tests;
4. replay test billing events including duplicate/out-of-order events;
5. generate a synthetic research report with provenance and non-ACTUAL performance basis where applicable;
6. execute delivery to test destinations with suppression/idempotency cases;
7. verify monitoring observations;
8. activate publication kill and prove delivery stops without deleting evidence;
9. restore publication and verify state consistency;
10. roll back application to the prior known-good artifact;
11. verify customer tombstones/suppression/entitlements are unchanged by application rollback;
12. archive the evidence bundle and mark the release **not production-approved** until explicit approval is granted.

## Secrets/config ownership matrix

| Class | Canonical owner/control | Versioned in Git | Staging/production shared |
|---|---|---:|---:|
| application code | Git/release artifact | yes | artifact may be same |
| non-secret config | environment manifest/IaC | yes | values may differ |
| vendor API secrets | secret manager | no | no |
| auth/session secrets | secret manager/KMS | no | no |
| billing credentials | secret manager | no | no |
| delivery credentials | secret manager | no | no |
| customer data | production data stores | no | no |
| synthetic test data | staging fixtures | fixtures only | no |
| release evidence | immutable evidence store | hashes/metadata only | environment-specific |

## NO-GO conditions

A commercial production release is blocked when any of the following applies:

- explicit user approval for production activation has not been given;
- unresolved high-severity CI/security failure;
- unknown build/artifact/config identity;
- staging artifact differs from the proposed production artifact without a new rehearsal;
- unresolved environment drift;
- secrets are shared across staging and production in a way that breaks revocation/isolation;
- entitlement isolation or billing reconciliation fails;
- report provenance/performance evidence gate fails;
- delivery suppression/idempotency fails;
- restore drill/publication-kill evidence is stale or failing;
- required vendor rights remain unverified for the planned output;
- required external-review reference is missing;
- rollback target is unavailable;
- any commercial release path can enable or require live brokerage execution.

## Follow-on implementation after approval

Only after the architecture is reviewed should implementation choose concrete AWS resources/IaC. Likely future work includes environment manifests, deployment roles, artifact signing/hashing, drift checks, staging release rehearsal automation, evidence bundling, and rollback drills. None of that should activate production or paid services without explicit approval.
