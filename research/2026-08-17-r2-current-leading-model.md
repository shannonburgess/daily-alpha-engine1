# Daily Alpha R2 Current Leading Model — Research Checkpoint

Research only. Nothing here is merged to production, deployed, or authorized for live trading.

## Current leading architecture

The strongest current research architecture is a risk-capped long-runner model:

- Normal entry: fresh 20-day breakout
- ADX >= 17 and rising versus prior day
- Efficiency >= 0.20
- RSI <= 80
- Bullish adaptive trend
- Two completed bullish trend bars before entry
- Close-location filter >= 0.65 in the current risk-cap champion
- Earnings Gap & Go sleeve preserved separately
- Initial size: 2 units
- Add +1 unit at +1 ATR when trend remains constructive
- Add +1 unit at +2 ATR when trend remains constructive
- No +3 ATR harvest in the current champion
- No early failed-breakout exit in the long-runner research architecture
- No bear-flip exit in the long-runner research architecture
- Primary trend exit: close below prior 55-day low
- Hard close-based risk cap: exit when close <= entry - 0.75 * canonical initial risk distance
- Canonical Daily Alpha 1R definition remains unchanged: initial two-unit risk based on entry close to prior 10-day low

## Current champion metrics

Risk-cap search universe: 60 broad liquid U.S. equities split deterministically into 38 search names and 22 held-out names.

### Search set, 2022-2024
- Trades: 168
- Win rate: 39.88%
- Average winner: 6.44R
- Average loser: 1.28R
- Expectancy: +1.80R/trade
- Profit factor: 3.35
- Worst trade: -3.12R

### 2025 validation on search names
- Trades: 72
- Win rate: 31.94%
- Average winner: 4.22R
- Average loser: 1.30R
- Expectancy: +0.46R/trade
- Profit factor: 1.52

### Held-out symbols, 2022-2025
- Trades: 126
- Win rate: 34.13%
- Average winner: 6.18R
- Average loser: 1.29R
- Expectancy: +1.26R/trade
- Profit factor: 2.48
- Worst trade: -4.79R

### 2026 YTD stress test across all 60 names
- Trades: 72
- Win rate: 51.39%
- Average winner: 2.77R
- Average loser: 1.24R
- Expectancy: +0.82R/trade
- Profit factor: 2.36
- Worst trade: -2.68R

This model therefore currently clears both research targets in the held-out set and in 2026 YTD: average winner >2R and profit factor >2.0, with positive expectancy.

## Entry-quality confirmation

A separate quality-filter search also found six strict configurations that cleared >2R average winner and >2.0 profit factor in held-out symbols and 2026. Its champion used:
- 20-day breakout
- ADX >=17 and rising
- Efficiency >=0.20
- RSI <=80
- Relative volume >=1.20
- No +3ATR harvest
- Long-runner management

That model produced on held-out symbols: 5.59R average winner, +1.64R expectancy, PF 2.60; in 2026: 2.81R average winner, +0.86R expectancy, PF 2.25.

## Important caveat

The 2025 validation year is the weak spot. The risk-cap champion's 2025 PF was 1.52, so this is not yet ready for production. The next requirement is to understand the 2025 regime failure and then run a larger universe / walk-forward confirmation without changing the rules to fit 2025 after the fact.

## Current decision

Do not modify production v2.4/v2.5 yet. The current leading research hypothesis is:

20D breakout + ADX17 rising + quality filter + 55D trend exit + hard close-based risk cap, with no early failed-breakout exit and no automatic +3ATR harvest.
