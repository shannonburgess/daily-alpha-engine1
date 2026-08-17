# Commercial Delivery Reliability Gate

Status: commercial-beta staging design only. No production deployment or customer delivery is enabled by this document.

Tracks: #81 and #87.

## Critical customer-visible events

The commercial beta should treat at least the following as observable delivery events:

- pre-market research note;
- end-of-day brief;
- report/archive availability;
- entitlement/access availability.

Each event should carry a stable delivery ID and customer-impact correlation ID so a failed or duplicate delivery can be traced across scheduler, publisher, archive and messaging systems.

## SLO evidence model

An SLO objective defines tolerances rather than hard-coding business promises into execution logic:

- maximum delivery lateness;
- maximum age of the source data at delivery time;
- duplicate-delivery tolerance, normally zero for customer communications.

An observation records the scheduled time, actual delivery time, source `as_of` time, correlation ID and duplicate count.

The repository evaluation fails closed when:

- no successful delivery timestamp exists;
- no source timestamp exists;
- the delivery exceeds the configured lateness tolerance;
- the research source is older than the configured freshness tolerance;
- duplicate delivery exceeds tolerance.

A missing observation is not evidence of reliability. Commercial readiness requires explicit passing observations.

## Staging validation plan

1. Generate a stable correlation ID before publication begins.
2. Persist the scheduled delivery time and canonical research-run ID.
3. Preserve the source-data `as_of` timestamps used to render the report.
4. Record archive completion separately from outbound delivery completion.
5. Exercise an intentional publication failure and verify it creates a detected failed observation.
6. Retry the failed publication with the same canonical delivery identity and verify idempotent behavior.
7. Verify a retry does not mutate the paper ledger or send duplicate customer content.
8. Test stale-source handling and prove the report is blocked or clearly failed rather than appearing current.
9. Retain evidence from restore/replay drills with the same correlation model.
10. Do not define a public SLA until operating evidence and commercial/legal review support it.

## Follow-on engineering

The evaluator in `daily_alpha.commercial_reliability` is intentionally provider-neutral. A later staging PR should map real publisher/archive/email events into these observations and store them in an immutable delivery audit history. Production monitoring, alarms, backup/restore drills and incident escalation remain separately approval-gated.
