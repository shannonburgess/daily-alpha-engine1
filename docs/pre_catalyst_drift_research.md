# Pre-Catalyst Drift Research

This sleeve tests whether **publicly scheduled corporate catalysts** create repeatable pre-event drift before the broader market fully reacts. It is research-only and cannot authorize a paper or live trade.

## Point-in-time rule

Every event must preserve `event_known_date`, the first date/time the event was publicly disclosed. The event cannot influence Daily Alpha before that timestamp. This is the core anti-lookahead control.

Preferred sources are issuer investor-relations pages, official filings/press releases, or another timestamped public source. Preserve source identity, first-seen timestamp, event date, and a reproducible source reference/hash where practical. Do not backfill an event calendar using information that was not public at the research decision timestamp.

## Initial event classes

- investor / analyst days
- named conferences
- product launches and keynotes
- public regulatory milestones
- other issuer-disclosed scheduled events

Earnings remains in the separate v2.4 earnings sleeve.

## Research windows

Measure T-20, T-15, T-10, T-5 through T-1 using only information known by each observation date. Test a pre-event exit separately from holding through the event so event-day gap risk is not mixed with the pre-catalyst drift hypothesis.

## Features

- excess return versus SPY and sector benchmark
- relative-strength acceleration
- relative volume / accumulation
- distance to prior 20-day high
- frozen Daily Alpha trend state
- ORATS call positioning, IV, skew, and term structure when timestamp-aligned and liquid

Initial output classes are `PRE_CATALYST_WATCH` and `PRE_CATALYST_RUN`. These are research labels, not execution instructions. Future research can separately test `EVENT_CARRY` and `SELL_THE_NEWS` only if the data supports them.

## Historical test design

Build the event set first, preserving the date each catalyst became public, then freeze the sample before measuring returns. Compare each event against matched non-event controls by sector, market-cap/liquidity, trend state, and broad-market regime. Report 1d/5d/10d pre-event excess return, MFE/MAE, hit rate, transaction-cost sensitivity, and performance by event type and lead time.

Separate raw anticipation effects from signals that simply rediscover ordinary momentum. The key falsification test is whether the catalyst information adds incremental out-of-sample value after controlling for the existing R2/trend score.

## Promotion / kill gate

Promote only for further research if the point-in-time catalyst overlay adds stable incremental information across walk-forward/holdout periods and does not depend on a few spectacular product launches or conferences. Kill the hypothesis if the apparent effect disappears after proper first-public-date reconstruction, matched controls, or realistic costs.
