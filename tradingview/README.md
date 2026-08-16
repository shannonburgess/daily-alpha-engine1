# Daily Alpha TradingView Strategy

## Canonical candidate

`da_turtle_20_10_v1_9.pine` is the current Daily Alpha Pine candidate selected after manual cross-stock validation.

### Initial long-entry gates

- Underlying close >= $25
- Fresh 20-bar Turtle breakout on a confirmed bar
- In-house adaptive SuperTrend-style state bullish
- ADX(14) >= 25
- RSI(14) <= 80

### Trade management

- 50% starter on initial qualified entry
- +25% after a confirmed close at +1 entry ATR
- +25% after a later confirmed close at +2 entry ATR
- Harvest 25% of the fully built position after a later confirmed close at +3 entry ATR
- After harvest, protect the runner at weighted-average break-even on a confirmed-close basis
- Final exit on 10-bar Turtle exit, adaptive-trend bearish flip, failed-breakout exit, or break-even protection

### Validation notes

The following extra Pine filters were tested and rejected as alpha gates because they did not consistently improve weak names without adding unnecessary complexity:

- 0.5 ATR close stop
- 20-day relative-strength filter vs SPY
- weak EMA uptrend gate
- strong 20/50 EMA uptrend gate
- $50M 20-day average dollar-volume gate
- trend-efficiency threshold

Underlying dollar volume should remain an execution/liquidity screen upstream, not a Pine alpha gate.

### Webhook status

The canonical script can emit the full paper-only runner lifecycle when `Attach Daily Alpha Runner Webhook Messages` is enabled:

- `ENTRY_LONG`
- `ADD` with `position_fraction=0.25`, `runner_stage=ADD_1_ATR`
- `ADD` with `position_fraction=0.25`, `runner_stage=ADD_2_ATR`
- `PARTIAL` with `position_fraction=0.25`, `runner_stage=HARVEST_3_ATR`
- `EXIT`

The AWS Pine ingress contract accepts and sanitizes these actions, but ingress still does not authorize trading or mutate the paper ledger. A separate paper-only processor must be added before `ADD` or `PARTIAL` can change a paper position.

Webhook order messages remain disabled by default until end-to-end SQS validation is complete.

No live brokerage execution is enabled.
