# Daily Alpha Canonical Research Facts V1

## Purpose

Not every useful investment input has the same authority. Daily Alpha therefore preserves the epistemic quality of research data instead of flattening primary filings, normalized vendor fundamentals, analyst estimates, news summaries, and alternative data into one undifferentiated feature stream.

## Domains

V1 covers:

- fundamentals
- estimates and revisions
- macroeconomic data
- news and catalysts
- institutional activity
- behavioral / alternative data

These inputs use the permanent Security Master identity, provider-independent data contracts, and strict point-in-time boundaries established in earlier stages.

## Research fact candidate

A `ResearchFactCandidate` records:

- security or global subject key
- domain and metric
- stable fact key
- fact value
- period end when applicable
- unit
- revision identity when applicable
- publication time
- time Daily Alpha received the fact
- source authority
- provider and upstream independence group
- provider/source version
- source observation ID
- confidence
- primary document identity when the fact claims primary authority

Future fiscal periods are allowed for estimates because the estimate can be known today about a future period. Publication and known times may never exceed the evaluation `as_of` boundary.

## Quality classes

Canonical research facts retain one of four quality states:

- `VERIFIED_PRIMARY`
- `CORROBORATED`
- `SINGLE_SOURCE`
- `BLOCKED`

This quality is available to future quantitative features and research agents. A single-source alternative-data point must not be treated as equivalent to a regulator-published fact.

## Domain defaults

### Fundamentals

Regulatory or issuer-primary facts can be verified directly. Normalized vendor facts can be used at lower authority, with independent corroboration preferred.

### Estimates and revisions

These are often licensed/vendor-native data. A single source can be retained at warning grade, while independent agreement improves quality. Point-in-time revision identity is preserved.

### Macro

Official macro release facts require regulatory/government/central-bank primary authority in V1. Vendor-normalized copies cannot become the canonical official release by themselves.

### News and catalysts

Regulatory or issuer-primary facts outrank summaries. Secondary/news-provider facts remain lower authority and conflicts with primary evidence are surfaced explicitly.

### Institutional activity

Regulatory-primary ownership/transaction facts are highest authority. Normalized ownership datasets retain lower authority unless corroborated.

### Behavioral / alternative data

Alternative data can be valuable but generally lacks a single authoritative source. Single-source observations remain warning grade; independent corroboration can raise them to `CORROBORATED`, but not to primary-verified status.

## Conflict and corroboration

The reconciler selects no more than one candidate per upstream independence group. Multiple APIs backed by the same upstream source do not create false confidence.

Primary conflicts block canonicalization. A secondary source that disagrees with primary evidence cannot replace the primary fact and is surfaced as a warning.

Non-primary sources can be reconciled through independent agreement. Exact agreement is the default; optional absolute numeric tolerance can be used for controlled rounding differences when explicitly configured.

## Point-in-time revisions

A later revised fact does not overwrite what was knowable earlier. Publication time, known time, period end, and revision identity are part of the historical record so future replay and attribution can reconstruct the information set that actually existed at each decision boundary.

## Current scope

This stage does not select or purchase data vendors, call live APIs, deploy AWS, alter SH24/SH25, modify TradingView, mutate PAPER execution, connect a broker, automate options, or enable live trading.

## Next stage

Stage 4F should build the deterministic Feature Store over canonical market state, event state, and research facts. Raw provider payloads should not flow directly into investment agents.
