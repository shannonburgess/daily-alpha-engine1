# Daily Alpha commercial email delivery controls

Status: **planning / commercial-beta readiness only**. This document does not activate a provider, modify DNS, send customer email, publish a website, or make a legal/compliance conclusion.

Tracks: #81, #87, #88, #97, #103, #116, #145, #157, #163.

## Purpose

Daily Alpha needs a delivery control plane that can prove not only that a report was generated, but that each customer-visible message was eligible to be sent, was not duplicated, respected preference/suppression state, and produced an auditable terminal delivery outcome.

The delivery layer must remain provider-neutral so business logic is not coupled to one email vendor.

## Trust boundaries

1. **Research artifact service** creates an immutable `REPORT_ID`, content hash, methodology/provenance reference and delivery-ready render.
2. **Identity / entitlement service** resolves `CUSTOMER_ID`, verified destination, active entitlement and tenant boundary.
3. **Preference / suppression service** resolves whether the requested delivery surface is currently allowed.
4. **Delivery orchestrator** creates an idempotent recipient-delivery record and calls a provider adapter.
5. **Provider adapter** maps provider-specific request/response/webhook fields into canonical delivery events.
6. **Delivery ledger** stores immutable attempts and current terminal state without rewriting historical evidence.

No research artifact should contain raw recipient email addresses.

## Canonical recipient-delivery state

Suggested states:

- `QUEUED`
- `SEND_ALLOWED`
- `SUPPRESSED`
- `SENT`
- `DELIVERED`
- `SOFT_BOUNCE`
- `HARD_BOUNCE`
- `COMPLAINT`
- `RETRY_PENDING`
- `DEAD_LETTER`
- `DATA_ERROR`
- `CANCELLED_ENTITLEMENT`
- `CANCELLED_PREFERENCE`

A provider's arbitrary status string must never become the system of record directly; map it through a versioned adapter.

## Minimum delivery record

Each recipient-delivery record should carry:

- `delivery_id`
- `report_id`
- `customer_id`
- `destination_ref` (privacy-minimized reference; not raw address in research storage)
- `surface` (`MORNING_REPORT`, `EVENING_REPORT`, `WATCHLIST_DIGEST`, `SERVICE_NOTICE`, etc.)
- `template_version`
- `content_hash`
- `provenance_manifest_id`
- `entitlement_decision_id`
- `preference_decision_id`
- `suppression_decision_id`
- `scheduled_at`
- `attempted_at`
- `provider_adapter_version`
- provider-neutral `message_correlation_id` when available
- `delivery_state`
- `terminal_reason`
- `retry_count`
- `created_at` / `updated_at`

## Idempotency contract

The logical send key should be deterministic, for example:

`sha256(report_id | customer_id | surface | template_version)`

Requirements:

- repeated scheduler invocation cannot create another logical send;
- provider timeout after acceptance cannot trigger a blind duplicate send;
- webhook replay cannot duplicate a state transition;
- a retry must re-check entitlement, preference and suppression immediately before provider submission;
- report regeneration with a materially different artifact must use a new `REPORT_ID` or explicit new content/version identity, not silently reuse the original key.

## Preference and suppression precedence

Before every optional research send:

1. customer exists and destination is verified;
2. account/session state is valid for delivery;
3. entitlement allows the surface;
4. destination is not globally suppressed;
5. surface-specific preference permits delivery;
6. report/data provenance is deliverable and not fail-closed;
7. idempotency key has no prior terminal/accepted send.

Any failed check produces a deterministic no-send reason.

Suggested suppression rules for the engineering model:

- `HARD_BOUNCE` -> immediate suppression pending verified destination correction;
- `COMPLAINT` -> immediate suppression for optional research delivery;
- repeated `SOFT_BOUNCE` -> threshold-based suppression after a versioned policy count/window;
- deletion/tombstone -> permanent no-send unless a separately verified new customer/destination lifecycle is created;
- no automatic unsuppression from import, retry, restore, or provider state drift.

## Unsubscribe / preference endpoint contract

The product should support a provider-neutral preference mutation contract before public beta. It can be implemented behind either an authenticated session or a signed, expiring token.

Required properties:

- tenant-safe customer binding;
- surface-specific change with a canonical global optional-research opt-out;
- replay-safe mutation ID;
- immutable acknowledgement/audit record;
- immediate effect on queued-but-not-yet-sent optional research;
- no ability to alter another customer's state by token/customer-ID substitution;
- backup restore reconciles against current suppression/tombstone state before delivery resumes.

The exact legal wording and jurisdiction-specific behavior remain an external-review item under #97.

## Provider webhook contract

Normalize provider events into a canonical envelope:

```json
{
  "event_id": "provider-or-derived-id",
  "provider": "PROVIDER_NAME",
  "provider_adapter_version": "v1",
  "received_at": "timestamp",
  "message_correlation_id": "opaque-provider-id",
  "event_type": "DELIVERED|SOFT_BOUNCE|HARD_BOUNCE|COMPLAINT|OTHER",
  "raw_event_hash": "sha256",
  "signature_verified": true
}
```

Rules:

- reject or quarantine malformed events;
- verify provider webhook authenticity when the selected provider supports signing;
- de-duplicate by provider event ID and/or deterministic raw-event hash;
- never interpret an unknown event as successful delivery;
- preserve the raw-event hash and normalized result for audit without unnecessarily persisting sensitive payload fields.

## Retry and dead-letter policy

- retry only explicit transient transport/provider failures;
- use bounded backoff;
- re-check entitlement/preference/suppression at every retry;
- terminal hard bounce/complaint is not retriable;
- malformed callback or ambiguous acceptance becomes `DATA_ERROR` / manual-review path rather than guessed success;
- dead-letter entries retain enough correlation metadata to replay safely after remediation.

## Sender-authentication readiness evidence

Before public customer email is enabled, production launch evidence should include the selected sender/domain state for:

- SPF
- DKIM
- DMARC
- aligned authenticated From / Return-Path behavior
- environment-specific sender identities
- bounce/complaint webhook configuration
- provider credential storage/rotation/revocation

A successful test message alone is insufficient evidence that sender authentication is correctly configured.

This repository should not modify DNS or purchase/activate a provider without explicit approval.

## Observability / SLO candidates

Measure separately from report-generation success:

- eligible recipients
- suppressed recipients by reason
- send attempts
- provider acceptance rate
- delivered rate where callback evidence exists
- soft/hard bounce rate
- complaint rate
- duplicate-prevention count
- retry / dead-letter count
- p50/p95 generation-to-provider-acceptance latency
- p50/p95 generation-to-delivery-callback latency where measurable

Never label `SENT` as `DELIVERED` unless provider evidence supports that distinction.

## Privacy and lifecycle integration

- raw destinations live in the identity/customer store, not research result files;
- analytics use `customer_id`, `delivery_id`, coarse state, and minimally necessary metadata;
- export/deletion workflows include preference and suppression evidence according to the versioned data-lifecycle policy;
- tombstone/restore reconciliation from #157/#158 runs before queued deliveries are resumed after recovery;
- delivery logs must not leak authentication tokens, unsubscribe tokens, card/billing data, or API secrets.

## Commercial-beta acceptance tests

The provider-neutral control plane is ready for provider-specific staging only when tests demonstrate:

1. one report/customer/surface cannot be duplicated by scheduler retry;
2. provider callback replay is idempotent;
3. hard bounce immediately suppresses later optional-research sends;
4. complaint immediately suppresses later optional-research sends;
5. preference change before retry cancels the queued retry;
6. entitlement loss before retry cancels the queued retry;
7. cross-tenant preference/suppression mutation is rejected;
8. malformed/unknown callbacks do not become successful delivery;
9. backup/restore reconciliation cannot resurrect a deleted or suppressed destination;
10. delivery ledger can reconstruct the exact report/provenance/template/entitlement/preference decision used for each attempt;
11. no test requires a paid account, customer list, public DNS modification, or real customer email.

## Explicit no-go conditions

Do not activate public/customer delivery if any of these remain unresolved:

- sender-authentication evidence missing;
- entitlement or suppression check can be bypassed;
- duplicate send is possible after provider timeout/retry;
- webhook authenticity/replay behavior is undefined;
- deleted/suppressed recipients can be resurrected by restore/import;
- delivery state cannot be tied to immutable report/provenance evidence;
- provider credentials are not stored/rotated under the production secret-management policy;
- launch-specific disclosure/terms/privacy/support/external-review requirements under #97 are incomplete.

## Safety boundary

This specification is architecture and test planning only. No email service purchase, paid account, DNS change, public sender activation, customer outreach, website publication, AWS production deployment, TradingView change, capital deployment, or live-trading change is authorized by this document.