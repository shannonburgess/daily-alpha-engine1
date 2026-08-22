# Pre-Catalyst Drift — Point-in-Time Manifest Build Plan

Status: research-only. This document does not authorize paper/live entries.

## Objective
Construct a frozen historical event manifest before computing any PRE_CATALYST performance. The manifest must preserve exactly when a scheduled non-earnings catalyst first became publicly knowable and must retain later revisions/cancellations without overwriting history.

## Initial event classes
Start with the most auditable issuer-originated events:
1. investor / analyst days;
2. issuer-announced named conferences or company-hosted presentations;
3. product launches / keynotes with a scheduled date;
4. issuer-disclosed regulatory or corporate milestones with a scheduled public date;
5. other issuer-disclosed scheduled events that can be independently timestamped.

Exclude earnings, which remain in the separate v2.4 earnings sleeve.

## Canonical manifest record
Each event record must contain at minimum:
- `event_id` — deterministic hash over issuer, event type, scheduled timestamp and first-public evidence;
- `symbol`;
- `event_type`;
- `event_name`;
- `scheduled_at` — timezone-aware scheduled event timestamp/date as publicly disclosed;
- `first_public_at` — earliest reproducible timestamp at which the event was publicly knowable;
- `first_seen_at` — timestamp Daily Alpha's evidence collector first observed the source in reconstruction;
- `source_url` — absolute HTTPS issuer/regulator/official-event source;
- `source_sha256` — hash of the archived source evidence;
- `source_kind` — issuer IR / SEC filing / official event page / regulator / other reviewed official source;
- `status` — SCHEDULED / RESCHEDULED / CANCELED / COMPLETED / UNKNOWN;
- `supersedes_event_id` when a later disclosure changes the schedule;
- `notes` limited to factual provenance/reconstruction details.

## Source priority
Use sources in this order when available:
1. issuer investor-relations press release / event page;
2. SEC filing or official regulator notice;
3. issuer-hosted webcast registration/page;
4. official conference/event organizer page naming the issuer;
5. secondary media only as corroboration, not as the sole first-public source unless no primary record can be reconstructed and the event is explicitly tagged lower-confidence.

## No-lookahead rules
- No event may be active before `first_public_at`.
- Later schedule revisions must create a new evidence state; do not rewrite the original public-known timestamp.
- Canceled/rescheduled events remain in the immutable manifest history.
- Research features for date T may use only manifest records/evidence with `first_public_at <= T`.
- Do not use current IR calendars to infer that an older event was knowable earlier.
- Freeze the manifest version/hash before calculating returns or tuning PRE_CATALYST thresholds.

## First cohort construction
Build an initial feasibility cohort across liquid Daily Alpha universe names with emphasis on event-rich sectors, but do not select events based on subsequent returns.

Target first-pass sample:
- at least 100 unique events if feasible;
- at least 30 issuers;
- multiple sectors and years;
- explicit count by event class and source kind;
- retained zero/negative examples and canceled/rescheduled events.

If the public evidence set cannot reach a credible N without retrospective/manual judgment, stop and record the data-feasibility failure rather than lowering the provenance standard.

## Outcome windows
After the manifest is frozen, measure independently:
- T-20 to T-1;
- T-15 to T-1;
- T-10 to T-1;
- T-5 to T-1;
- pre-event exit versus hold-through-event as separate experiments.

Report raw and excess returns versus SPY and sector benchmark, MAE/MFE, winner rate, median/mean, tail outcomes and results excluding the best event.

## Matched controls
Each event observation requires a non-event control design using only point-in-time information. Match or stratify on:
- sector;
- liquidity / ADV;
- market-cap bucket when available point-in-time;
- R2 trend state / ADX / efficiency;
- recent relative strength;
- realized volatility;
- distance to recent high;
- broad market regime.

The PRE_CATALYST effect must add incremental information beyond ordinary R2/momentum. A simple event cohort with no matched comparison is not promotion evidence.

## ORATS features
Option IV/skew/term-structure/flow features remain optional research enrichments and must be omitted or marked DATA_ERROR when historical executable-side ORATS evidence is unavailable. Do not backfill with synthetic option prices for promotion decisions.

## Acceptance criteria for first empirical run
- manifest is immutable/versioned and hashed before outcomes are computed;
- every included event has reproducible first-public evidence;
- revisions/cancellations are preserved rather than overwritten;
- no event is scored before it was public;
- explicit N and source/event-type distribution are reported;
- matched-control results and best-event exclusion are included;
- any manual exclusions are predeclared and auditable;
- no output is connected to paper/live execution.

## Kill / defer conditions
Defer or kill the sleeve if:
- point-in-time event reconstruction is too sparse or subjective;
- apparent alpha disappears versus matched R2/momentum controls;
- results depend on one issuer/event class/year;
- event provenance cannot be redistributed or retained for the intended commercial research surface;
- performance requires future-known schedule revisions or other lookahead.