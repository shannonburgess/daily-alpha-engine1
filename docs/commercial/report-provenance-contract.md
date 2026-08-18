# Daily Alpha Report Provenance Contract

Status: staging/research design. No public publishing, customer launch, production deployment, or legal/compliance conclusion is authorized by this document.

## Purpose

Every future customer-visible research artifact should be traceable to the exact source evidence, strategy/model version, methodology version, code/build identity, non-secret configuration identity, and delivery/archive record that produced it. The manifest is evidence metadata; it is not a performance claim and does not make the underlying report correct merely because it is reproducible.

## Manifest lifecycle

1. Collect immutable or decision-time source evidence with source cutoff, retrieval timestamp, freshness classification, schema version, evidence locator, and hash where archival rights permit.
2. Generate the structured research output under frozen strategy/model/methodology/config versions.
3. Build and validate one `ReportProvenanceManifest` for the artifact.
4. Fail closed if required evidence is missing, invalid, stale beyond the report policy, or classified DATA_ERROR/DATA_UNAVAILABLE for a field required to support the customer-visible statement.
5. Run readability/content QA on the report.
6. Persist the report and manifest together using immutable identities; retries must reuse the same report/build/evidence identity rather than create duplicate history.
7. Record delivery correlation separately but link it to the manifest/report ID.

## Required separation

Performance basis must be one of `ACTUAL`, `PAPER`, `BACKTEST`, `HYPOTHETICAL`, or `NONE`. A report may contain multiple separately labeled evidence sections, but one performance line must never aggregate these bases. Any future combined report must retain distinct provenance/manifests per basis-specific artifact.

## Data-quality behavior

`FRESH` means the source passed the report-specific freshness policy. `STALE`, `DATA_ERROR`, and `DATA_UNAVAILABLE` remain explicit evidence states and are never silently converted to a healthy source. The current module exposes a degraded footer state when any source record is non-fresh; future channel-specific publication policy may be stricter and block the entire report.

## Replay and revisions

A revised upstream observation creates new evidence and therefore a new evidence hash. It must not overwrite the decision-time record used for the historical report. Material strategy, model, ranking, benchmark, cost, option-mark, or methodology changes also create a new version identity and require any related performance claim to be revalidated under #86/#113.

Where provider terms prevent archival of raw source payloads, store the allowed decision-time fields, source identity, source/retrieval timestamps, schema version, and a content/evidence hash sufficient to explain what the system observed. Do not pretend full replay is possible when the raw source cannot be retained.

## Storage and retention proposal

- Immutable report artifact and provenance manifest share the same report ID namespace.
- Manifest records contain no customer PII, payment data, secrets, tokens, private provider credentials, or privileged AWS details.
- Customer delivery records reference the report ID / delivery correlation ID rather than duplicating the report content into account metadata.
- Retention/deletion requirements for customer/account data remain governed by #85/#103; research/performance evidence retention is a separate recordkeeping question and remains subject to #97 external review before launch.

## Customer-safe footer

The initial safe footer surface is limited to report ID, strategy/model/methodology version, source cutoff, performance basis, evidence hash, and a compact data-quality state. Internal evidence locators, delivery identifiers, customer identifiers, credentials, and infrastructure details are excluded.

## Staging acceptance criteria

- identical immutable inputs and versions produce the same canonical manifest hash;
- source ordering does not change the hash;
- any source-content/version change changes the hash;
- missing source evidence fails closed;
- mixed/unknown performance bases are rejected;
- stale/error source state remains visible;
- customer-safe footer does not expose archive/delivery/internal infrastructure identifiers;
- at least one morning brief, EOD brief, and performance artifact is later replayed in staging from its recorded manifest before commercial beta can pass #81.

Tracks #81, #86, #87, #103, #113, and #116.
