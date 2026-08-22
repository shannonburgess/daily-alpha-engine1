# Daily Alpha Commercial Beta — Customer Data Lifecycle

Status: internal design / staging readiness only. This document does not make a legal, regulatory, privacy, certification or compliance conclusion and does not authorize customer onboarding or production processing.

Tracks: #157, #103, #81.

## Objective

Define one provider-neutral lifecycle for customer-linked data so authentication, entitlements, billing metadata, delivery audit, support, analytics, backups and future customer requests cannot retain inconsistent or silently resurrected records.

## Principles

1. Collect the minimum data required for the research-subscription product.
2. Keep authentication separate from entitlement and keep payment credentials outside the application data model.
3. Every customer-linked record carries a canonical `customer_id` and tenant boundary.
4. Unknown lifecycle state fails closed for optional collection and privileged access.
5. Customer-data export/deletion operations are idempotent, auditable and tenant-isolated.
6. Backups and replay systems must not silently resurrect records that have reached a deleted/tombstoned state.
7. Retention periods, consent language and launch-specific privacy obligations remain external-review questions under #97.

## Data-class registry contract

Before beta, maintain a versioned registry with one row per class containing:

- `data_class`
- `system_of_record`
- `purpose`
- `minimum_fields`
- `sensitivity`
- `allowed_roles`
- `allowed_services`
- `service_required` boolean
- `retention_state`
- `deletion_eligible` boolean
- `derived_replicas`
- `backup_treatment`
- `audit_stub_after_deletion`
- `external_review_note`

Minimum initial classes:

- account/profile identity metadata;
- authentication/session/security events;
- entitlement/subscription state;
- provider-neutral billing-event metadata;
- disclosure/terms/privacy acknowledgement evidence;
- report/newsletter delivery observations;
- customer preferences;
- support/admin case metadata;
- privacy-minimized product analytics;
- references from customer delivery records to immutable research/performance/provenance artifacts.

Raw card/payment credentials, brokerage credentials and unrelated personal financial-profile data are out of scope for the research subscription and must not enter this registry as normal application data.

## Lifecycle states

`ACTIVE_SERVICE`

Customer is entitled according to the independent entitlement service. Required service data may be processed; optional analytics still follows minimization rules.

`CANCELED_RETAIN_FOR_RECONCILIATION`

Entitlement is inactive. New optional analytics collection stops. Only minimum reconciliation, security, support and required audit records remain according to the unresolved launch-specific retention policy.

`DELETION_REQUESTED`

A privileged, auditable request exists. No destructive action occurs until the synthetic/staging validation gates and launch-specific review requirements are satisfied.

`DELETION_IN_PROGRESS`

The deletion orchestrator fans out idempotent operations to all registered stores and derived replicas. Each store returns a deterministic disposition.

`CONTENT_DELETED_AUDIT_STUB_RETAINED`

Active customer content has been removed from in-scope stores. A minimal tombstone/reconciliation stub remains only to prevent accidental replay/restore resurrection and to preserve integrity evidence where the final launch policy permits it.

`LEGAL_OR_SECURITY_HOLD`

Exception state requiring an explicit externally reviewed reason and privileged audit evidence. Repository logic must never infer this state automatically.

## Acknowledgement evidence

For terms/privacy/disclosure acknowledgement, store only the evidence needed for reproducibility:

- `customer_id`
- `document_type`
- `document_version`
- `document_hash`
- `acknowledged_at`
- `surface`
- `evidence_id`
- later update/withdrawal state where applicable

The repository must not assert that an acknowledgement pattern is legally sufficient; #97 resolves launch-specific requirements.

## Export manifest

A synthetic/staging export request should produce one machine-readable manifest containing:

- `request_id`
- `customer_id`
- `requested_at`
- `registry_version`
- every expected data class and system of record
- record counts or explicit `NONE`
- export artifact hashes
- failures / retries
- final reconciliation state

Cross-tenant access is a hard failure.

## Deletion reconciliation manifest

A deletion run should be replay-safe and emit:

- `request_id`
- `customer_id`
- `registry_version`
- target store / replica
- prior state
- operation attempted
- final state
- tombstone/evidence reference
- retry count
- operator/service identity
- completion timestamp

The run is not complete while any expected store is missing or returns an unknown state.

## Backup / restore rule

Restore drills must validate that records marked deleted/tombstoned are not silently returned to an active state. A restored older backup must be reconciled against the current lifecycle/tombstone ledger before customer access is re-enabled.

## Analytics minimization

Allowed beta analytics should use a pseudonymous stable customer identifier and only fields needed to measure acquisition, activation, engagement, delivery health, retention/churn and feature use. Do not copy free-text support content into analytics by default. Do not log authentication secrets, payment credentials, report private payloads or unnecessary profile attributes.

## Staging acceptance tests

Commercial beta remains NO-GO until synthetic tests prove:

1. customer A cannot enumerate, export, mutate or delete customer B data;
2. duplicate export/deletion requests are idempotent;
3. every expected store appears in the reconciliation manifest;
4. unknown store/lifecycle state fails closed;
5. a backup restore does not resurrect deleted active records;
6. acknowledgement evidence is deterministic and versioned;
7. billing metadata is structurally separated from payment credentials;
8. analytics events pass the minimum-field policy;
9. privileged destructive operations are auditable;
10. missing evidence fails the commercial-beta readiness gate.

## Explicit non-goals

This spec does not choose an identity, billing, analytics, CRM, support or storage vendor; set public retention periods; publish terms/privacy text; contact customers; process payment; deploy production; or claim legal/compliance approval.
