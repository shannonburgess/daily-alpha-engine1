# Daily Alpha TradingView Strategy

## Canonical candidate

`da_turtle_20_10_v2_3.pine` is the current Daily Alpha Pine candidate. It preserves the Turtle 20/10 + adaptive-trend + ADX/RSI + 50/25/25 runner framework and adds the selected Trend Efficiency gate.

The prior `da_turtle_20_10_v1_9.pine` remains in the repository as the frozen historical baseline.

### Initial long-entry gates

- Underlying close >= $25
- Fresh 20-bar Turtle breakout on a confirmed bar
- In-house adaptive SuperTrend-style state bullish
- ADX(14) >= 25
- RSI(14) <= 80
- 20-bar Trend Efficiency >= 0.20

### Trade management

- 50% starter on initial qualified entry
- +25% after a confirmed close at +1 entry ATR
- +25% after a later confirmed close at +2 entry ATR
- Harvest 25% of the fully built position after a later confirmed close at +3 entry ATR
- After harvest, protect the runner at weighted-average break-even on a confirmed-close basis
- Final exit on 10-bar Turtle exit, adaptive-trend bearish flip, failed-breakout exit, or break-even protection

### Execution/liquidity metadata

The Pine alpha decision remains separate from execution quality. The v2.3 ENTRY webhook includes the current 10-bar Turtle stop and 20-day average dollar volume as metadata so the paper-only instrument fallback engine can independently apply its execution/liquidity rules.

### Webhook status

The v2.3 script can emit the full paper-only runner lifecycle when `Attach Daily Alpha Runner Webhook Messages` is enabled:

- `ENTRY_LONG`
- `ADD` with `position_fraction=0.25`, `runner_stage=ADD_1_ATR`
- `ADD` with `position_fraction=0.25`, `runner_stage=ADD_2_ATR`
- `PARTIAL` with `position_fraction=0.25`, `runner_stage=HARVEST_3_ATR`
- `EXIT`

Webhook order messages remain disabled by default. Do not enable a recurring TradingView alert until the AWS processor contract has been promoted from v1.9 to v2.3 and a controlled staging test passes.

No live brokerage execution is enabled.
