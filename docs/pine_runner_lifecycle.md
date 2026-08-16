# Pine runner lifecycle contract

The TradingView ingress accepts the canonical Daily Alpha lifecycle actions:

`ENTRY_LONG -> ADD -> ADD -> PARTIAL -> EXIT`

This is an **ingress/normalization contract only**. Receiving any action does not authorize a trade, trigger paper execution, or enable live brokerage execution.

## Runner metadata

`ADD` and `PARTIAL` events must include:

- `position_fraction`: decimal fraction greater than 0 and at most 1.
- `runner_stage`: auditable stage identifier.

Canonical v1.9 stages:

- `ADD_1_ATR` with `position_fraction=0.25`
- `ADD_2_ATR` with `position_fraction=0.25`
- `HARVEST_3_ATR` with `position_fraction=0.25`

`ENTRY_LONG` and `EXIT` retain their existing payload shape.

## Safety boundary

Normalized queue records always preserve:

- `trading_authorized=false`
- `paper_execution_triggered=false`
- `live_trading_enabled=false`

The shared webhook secret is removed before queueing. A later SQS processor must explicitly validate portfolio state, risk, instrument selection, idempotency, and paper-ledger semantics before runner actions can mutate any paper position.
