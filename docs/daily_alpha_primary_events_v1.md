# Daily Alpha Primary-Source Event Authority V1

## Purpose

Material events can alter portfolio risk faster than ordinary factor data. Daily Alpha therefore treats event authority separately from generic sentiment or vendor summaries.

The platform distinguishes between the event itself and when information about the event became knowable. A future earnings date is valid point-in-time information when it was publicly announced before the evaluation boundary.

## Domains

V1 covers three material event domains:

- corporate actions
- earnings/events
- SEC filings

These domains use the provider-agnostic contracts built in Stage 4B and permanent `security_id` identity from the Security Master.

## Source authority

Every normalized event candidate carries one explicit authority class:

1. `REGULATOR_PRIMARY`
2. `ISSUER_PRIMARY`
3. `EXCHANGE_PRIMARY`
4. `VENDOR_NORMALIZED`
5. `SECONDARY`

Primary-source assertions require a durable source-document identity. This prevents an unlabeled summary from being promoted to primary evidence.

## Point-in-time semantics

An event candidate separates:

- `event_time`: when the event occurs or becomes effective
- `published_at`: when the source published the information
- `known_at`: when Daily Alpha received it

`event_time` may be in the future. `published_at` and `known_at` may not exceed the request's `as_of` boundary.

This distinction allows Daily Alpha to know about future earnings dates, splits, investor days, and other scheduled events without introducing look-ahead bias.

## Authority policy

### SEC filings

Regulatory primary evidence is required. Vendor copies are useful for normalization/search but cannot become canonical SEC facts on their own.

### Corporate actions

A regulator, issuer, or exchange primary source is required before the event becomes canonical.

### Earnings/events

Issuer-primary evidence can stand alone. If no primary source is available, two truly independent vendor upstream groups may provide a warning-grade canonical fact when they agree exactly. Vendor disagreement blocks canonicalization.

## Conflict rules

When primary evidence exists:

- primary evidence controls the canonical fact
- disagreement between primary sources blocks the event
- vendor disagreement with primary evidence does not replace primary truth, but is surfaced as an explicit warning

When only vendor evidence exists:

- independence is measured by upstream source group, not API count
- insufficient independent corroboration blocks
- disagreement blocks
- agreeing vendor-only earnings facts remain `WARNING`, not `PASS`, because a primary source is absent

## Output

`CanonicalEventState` records:

- permanent security ID
- domain and metric
- point-in-time boundary
- event key
- PASS / WARNING / BLOCKED
- canonical candidate and authority when allowed
- all candidate IDs
- selected providers and independent groups
- blockers and warnings
- deterministic state ID
- hard research-only/live-safety flags

A blocked state cannot carry a canonical event candidate.

## Current scope

This stage does not select or purchase event-data vendors, call SEC/issuer APIs, deploy AWS, alter SH24/SH25, modify TradingView, mutate PAPER execution, connect a broker, automate options, or authorize live trading.

## Next stage

Stage 4E should apply the same point-in-time/provider-independent architecture to fundamentals, estimates/revisions, macro, news/catalysts, institutional activity, and behavioral data before the deterministic Feature Store is built.
