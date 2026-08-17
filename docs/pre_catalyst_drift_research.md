# Pre-Catalyst Drift Research

This sleeve tests whether public scheduled corporate events create repeatable pre-event drift before the broader market fully reacts. It is research-only.

## Point-in-time rule

Every event must preserve `event_known_date`, the first public disclosure date. The event cannot influence Daily Alpha before that date. This is the core anti-lookahead control.

## Initial event classes

- investor / analyst days
- named conferences
- product launches and keynotes
- public regulatory milestones
- other issuer-disclosed scheduled events

Earnings remains in the separate v2.4 earnings sleeve.

## Research windows

Measure T-20, T-15, T-10, T-5 through T-1. Test pre-event exit separately from holding through the event so event-day gap risk is not mixed with the pre-catalyst effect.

## Features

- excess return versus SPY / sector
- relative-strength acceleration
- relative volume / accumulation
- distance to 20-day high
- Pine trend state
- ORATS call positioning, IV, skew, and term structure when available

Initial output classes are `PRE_CATALYST_WATCH` and `PRE_CATALYST_RUN`. Future research can separately add `EVENT_CARRY` and `SELL_THE_NEWS` if supported by data.
