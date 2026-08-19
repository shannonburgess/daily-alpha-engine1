# Pre-Catalyst Drift — Official Source Acquisition Specification

Status: research-only support for #72 / draft PR #135. This document defines how to acquire point-in-time scheduled-event evidence before any return test. It does not authorize a trade.

## Objective
Build a frozen historical event manifest from sources whose public timestamp can be defended. The research question is whether returns drift before a *known scheduled catalyst*; therefore retrospective event discovery without a reliable first-public timestamp is not usable promotion evidence.

## Source priority
1. **SEC EDGAR filing evidence** — issuer 8-K / 6-K / other public filing when the filing itself announces or attaches a scheduled investor day, conference, product event or regulatory milestone. Use EDGAR accession identity and acceptance/dissemination timestamp as the public-known anchor when the event schedule is contained in that filing.
2. **Issuer-owned investor-relations evidence** — press release, event-calendar entry or presentation published on the issuer's official IR domain. Preserve page/document bytes or a normalized archive artifact plus first-seen timestamp.
3. **Official event-organizer evidence** — only when the organizer itself publishes the issuer/date and the evidence can be archived point-in-time.
4. Secondary news/search results may help discover candidates but cannot establish `first_public_at` unless the underlying primary evidence is preserved.

## SEC EDGAR acquisition contract
The SEC's public `data.sec.gov/submissions/CIK##########.json` feed provides company submission history without an API key. The raw EDGAR submission header also exposes the filing acceptance timestamp. For any event sourced from EDGAR preserve:
- issuer CIK;
- accession number;
- form type;
- filing date;
- EDGAR acceptance datetime when available;
- primary document/attachment path containing the schedule;
- exact event date/time/timezone text as disclosed;
- normalized `scheduled_at`;
- source hash for the preserved filing/attachment bytes or canonical normalized extract;
- extraction version / parser commit;
- event revision/cancellation relationship when a later filing changes the schedule.

Do not infer a public-known time earlier than EDGAR acceptance/dissemination from the event date printed inside a filing.

## Issuer IR acquisition contract
For official IR pages/documents preserve:
- canonical issuer/CIK mapping;
- exact source URL;
- document/page title;
- first-seen timestamp from the acquisition process;
- publication timestamp only when displayed by the issuer and retained in source evidence;
- raw or normalized source hash;
- scheduled event date/time/timezone text;
- subsequent changed/canceled/rescheduled source evidence as a new revision.

A crawler first-seen timestamp is not evidence that the page was not public earlier. If no defensible publication timestamp exists, mark timestamp confidence accordingly and exclude from strict promotion evidence unless a separate official source anchors the date.

## Event acceptance rules
Accept an event into the frozen strict manifest only when:
- the event is non-earnings and belongs to a predeclared class;
- `first_public_at <= scheduled_at`;
- the source is official and hashable;
- date/time semantics are unambiguous enough for T-20/T-15/T-10/T-5 windows;
- revisions/cancellations are represented rather than overwritten;
- the event was knowable before the first research window used in an outcome calculation.

Otherwise retain the candidate in a rejected/deferred table with an explicit reason code.

## Deterministic IDs
Suggested event ID inputs:
`issuer_id | event_class | original_scheduled_at | first_public_at | source_identity`

Revisions should reference the original event ID and receive a new evidence/revision ID. Do not mutate the original evidence record.

## Acceptance tests before return analysis
- every strict-manifest row has official source identity and SHA-256 evidence;
- every event has timezone-aware `scheduled_at` and `first_public_at`;
- SEC-sourced rows preserve CIK/accession/form/acceptance evidence;
- no research feature or return is joined before the manifest hash is frozen;
- canceled/rescheduled events remain in audit history and are not silently deleted;
- retrospective-only discoveries remain excluded from strict promotion evidence;
- at least the target sample/distribution requirement from `pre_catalyst_manifest_build_plan.md` is met, or the study records `INSUFFICIENT_POINT_IN_TIME_SAMPLE`.

## Safety / legal boundary
This is a research data-lineage design, not a legal/compliance conclusion and not a statement about redistribution rights. Customer-facing use of any source remains separately gated by the commercial data-rights process.
