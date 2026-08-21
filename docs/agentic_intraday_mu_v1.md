# Daily Alpha Agentic Intraday V1 — MU pilot

## Objective

Create a fully isolated PAPER-only intraday laboratory to determine whether a deterministic,
agent-operated momentum process has repeatable edge in MU without changing or contaminating
Daily Alpha SH24/SH25 swing forward tests.

The pilot is intentionally narrow:

- account: `PAPER_AGENTIC_INTRADAY_V1`
- symbol: `MU` only
- instrument: shares only
- direction: long only for V1
- new option positions: prohibited
- averaging down: prohibited
- overnight positions: prohibited
- live trading: prohibited
- `trading_authorized=false`
- `live_trading_enabled=false`

## Session clock

All routing is resolved in `America/New_York` so daylight-saving changes do not alter the
market-session contract.

| Eastern | Pacific | Phase | Decision timeframe |
| --- | --- | --- | --- |
| 09:30-10:00 | 06:30-07:00 | `OPENING_2M` | 2 minute |
| 10:00-15:30 | 07:00-12:30 | `STANDARD_5M` | 5 minute |
| 15:30-15:50 | 12:30-12:50 | `MANAGEMENT_ONLY` | 5 minute management only |
| 15:50-16:00 | 12:50-13:00 | `FLATTEN_ONLY` | exits only |
| otherwise | otherwise | `CLOSED` | no new risk |

An open 2-minute position transfers to 5-minute management at 10:00 ET without resetting
entry price, stop, risk basis, high-water mark, MFE/MAE or lifecycle state.

## Context hierarchy

V1 separates context from execution:

1. Daily Alpha / OVTLYR daily context.
2. 15-minute intraday trend/regime context.
3. 2-minute execution signal during the first 30 minutes.
4. 5-minute execution signal after the first 30 minutes.

A 2-minute or 5-minute trigger can never authorize a PAPER entry by itself. Both daily and
15-minute context must already be approved.

The exact momentum signal formula is deliberately **not** part of this foundation PR. It will
be frozen and tested in the next PR so infrastructure/state rules cannot be conflated with
alpha-rule tuning.

## V1 risk envelope

The foundation uses conservative PAPER limits:

- maximum planned loss per new trade: 0.25% NAV
- maximum new intraday risk per day: 0.50% NAV
- maximum new trades per day: 2
- maximum notional per trade: 2% NAV
- company price floor: $10
- company 30-day average daily share volume: strictly greater than 1,500,000 shares
- one open MU intraday position at a time
- every long entry requires a positive stop strictly below entry price

The risk and notional ceilings both apply. Share quantity is the lower of the risk-limited and
notional-limited quantities. Rejected decisions have zero executable quantity.

## Agentic state machine

The durable state contract is:

`DISCOVERED`
-> `CONTEXT_APPROVED`
-> `WATCHING_2M` or `WATCHING_5M`
-> `ENTRY_TRIGGERED`
-> `RISK_APPROVED`
-> `PAPER_OPEN`
-> `MANAGED_5M` / `PARTIAL`
-> `EXITED`
-> `FORENSICS_COMPLETE`

Any pre-entry stage may terminate in `REJECTED`, which then proceeds to
`FORENSICS_COMPLETE`. Rejected candidates should eventually be followed counterfactually so
filter value can be measured rather than assumed.

## Isolation

This pilot does not add its account to the SH24/SH25 `SHADOW_MODELS` routing table and does
not modify `shadow_routing.py`. Its account identity is rejected if substituted with
`PAPER_SHADOW_V24`, `PAPER_SHADOW_V25` or any other account.

No AWS resource, TradingView alert, Pine source, production deployment or broker integration
is created by the foundation PR.

## Forward-test measurements

Once execution is connected, each accepted and rejected setup should retain:

- entry timeframe (`2M` or `5M`)
- session bucket
- daily context and 15-minute context
- sector/industry state
- relative volume and VWAP state when available
- trigger type
- entry, stop, shares, planned risk and notional
- exit and exit reason
- realized P/L and realized R
- MFE and MAE
- holding period
- rejection reason for non-trades

Primary evaluation cuts:

- 2-minute opening expectancy vs 5-minute expectancy
- opening vs morning vs midday vs late-session results
- Daily Alpha aligned vs non-aligned observations
- 15-minute context strength
- sector alignment
- accepted vs rejected expectancy

Do not promote strategy changes from a small sample. The initial review checkpoint is 30
closed trades; the first meaningful strategy review target is 50-100 closed trades.

## Next build step

PR 2 should implement the deterministic **MU Intraday Momentum Continuation** signal contract:

- daily context input
- 15-minute regime/trend qualification
- 2-minute opening trigger
- 5-minute standard-session trigger
- VWAP/relative-volume/extension controls
- explicit stop construction
- deterministic no-trade reason codes
- no ledger mutation yet until signal behavior is regression-tested
