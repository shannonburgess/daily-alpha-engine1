# Earnings EARLY Point-in-Time Universe Manifest Specification

Status: research-only support for #71 / draft PR #134. This specification exists to expand the EARLY sample without survivorship or lookahead leakage. It does not authorize any starter, confirmation rule, option trade, paper entry, or live entry.

## Purpose
The current 61-name screen is useful for falsification but is not a sufficient promotion sample. A broader cohort must be built from a frozen, point-in-time eligibility manifest so names are not selected because they are liquid/successful today or because later returns are known.

## Canonical manifest row
Each symbol/date eligibility interval should preserve at least:
- `symbol` — normalized historical ticker used by the price/event source;
- `issuer_id` — stable issuer identifier when available so ticker changes do not create a new company;
- `eligible_from` / `eligible_through` — inclusive eligibility interval known from the source methodology;
- `source_type` — exchange/index/vendor/public-universe source class;
- `source_reference` — immutable source reference or archived evidence identifier;
- `source_as_of` — timestamp/date when the eligibility evidence was valid;
- `source_hash` — SHA-256 of the preserved source artifact or normalized source rows;
- `delisted_flag` and `delisted_date` when known;
- `security_type` — common equity / ADR / other; ETFs must be excluded from this earnings cohort;
- point-in-time `price` and `average_daily_dollar_volume` evidence used for the research liquidity gate;
- `liquidity_window_end` strictly before or on the event decision date;
- `data_status` — AVAILABLE / DATA_ERROR / INSUFFICIENT_HISTORY.

## Eligibility rules
1. Membership/eligibility must be evaluated from evidence available at the event date.
2. Price and liquidity filters must use only trailing data available at that time.
3. A later delisting, bankruptcy, acquisition or ticker change must not remove the historical member from the cohort.
4. Data failure must remain a separate failure record; it must not be converted into a no-event observation.
5. If a point-in-time universe source cannot support historical membership with adequate lineage, that source may be used for exploratory recall only and its results cannot support promotion.

## Freeze-before-outcomes protocol
Before computing EARLY forward returns:
1. build the manifest and validate duplicate issuer/symbol intervals;
2. resolve ticker-change mappings without using future-return information;
3. freeze the exact manifest rows and compute a deterministic manifest hash;
4. record the runner commit/model version and frozen 60%/70% EARLY boundaries;
5. only then join earnings events and calculate T+1/T+2/5/10/20/40-day outcomes.

Any manifest revision after outcomes are observed requires a new manifest version/hash and complete rerun. Do not silently edit the promotion sample.

## Minimum QA / acceptance tests
- no event date precedes `eligible_from` or follows `eligible_through`;
- no liquidity window ends after the event date;
- no ETF/security type enters the single-company earnings cohort;
- duplicate issuer/ticker histories are deterministic and auditable;
- delisted historical members remain represented when source data exists;
- every excluded row has an explicit reason code;
- manifest hash changes when any membership/evidence row changes;
- event/outcome code consumes the frozen manifest rather than a current-day ticker list.

## Reporting requirements
Expanded EARLY output must report:
- total eligible issuers/symbol intervals;
- events by year/sector and security-source class;
- DATA_ERROR / insufficient-history counts;
- delisted/ticker-change representation;
- results with and without best/top-3 events;
- 2025 as a separate validation/falsification slice;
- present-day-universe-only result beside the point-in-time result so survivorship impact is visible.

## Kill / defer condition
If credible point-in-time membership cannot be reconstructed at useful scale, do not relax the evidence standard. Keep EARLY watch-only and label the cohort limitation explicitly.
