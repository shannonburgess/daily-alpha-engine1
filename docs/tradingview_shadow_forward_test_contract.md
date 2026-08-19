# Daily Alpha v2.4 / v2.5 Shadow Forward-Test Pine Contract

Status: **PAPER SHADOW / NOT ACTIVATED**

This document defines the source-side payload contract required before the isolated `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` books can be enabled for a prospective comparison. It does not choose a v2.5 strategy, choose a no-chase threshold, enable TradingView alerts, deploy AWS, or authorize live trading.

## Current repository gap

The current v2.4 Pine source emits the legacy runner webhook fields but does **not** yet emit the three shadow-control fields required by the backend contract:

- `model_id`
- `forward_test_start`
- `replay_max_price` on ENTRY events

A dedicated v2.5 Pine source is not yet present in the repository. Do not manufacture a v2.5 TradingView alert from research/backtest branches or from a chart carrying a historical simulated position.

## Required common start boundary

Both shadow models must:

1. start from a clean **FLAT** TradingView strategy state;
2. use the same declared `forward_test_start` date;
3. send that exact date on every tagged shadow event;
4. match the backend `DAILY_ALPHA_SHADOW_FORWARD_START` setting;
5. reject any event whose bar/event time predates the declared start.

The shared date is a synchronization boundary, not a performance-tuning parameter.

## Required model identities

- v2.4 control: `PAPER_SHADOW_V24`
- v2.5 challenger: `PAPER_SHADOW_V25`

A tagged v2.5 event must identify strategy version `2.5`. A tagged v2.4 control event must identify strategy version `2.4`. No untagged event may be silently migrated into either shadow book.

## ENTRY payload requirements

Every tagged shadow ENTRY must carry the legacy canonical fields plus:

```json
{
  "model_id": "PAPER_SHADOW_V24",
  "forward_test_start": "YYYY-MM-DD",
  "replay_max_price": 0.0
}
```

`replay_max_price` must be a finite positive numeric ceiling and cannot be below the signal price. The Pine/source strategy must supply the deliberately reviewed ceiling. The backend must never infer, widen, or guess it.

If the ceiling is absent, invalid, or lost in transit, an after-hours ENTRY may remain visibly armed but cannot be replay-filled.

## ADD / PARTIAL / EXIT payload requirements

Tagged lifecycle events must carry:

- `model_id`
- `forward_test_start`
- the canonical signal/action/version/timeframe/bar identity fields
- the canonical runner-stage / position-fraction fields where applicable

`replay_max_price` is an ENTRY no-chase field and is not required to invent a price ceiling for runner-management events. Runner events outside the tradable window still require fresh quote/state revalidation before paper mutation.

## Example v2.4 control ENTRY shape

```json
{
  "webhook_secret": "<configured in TradingView; never committed>",
  "signal_id": "<deterministic signal id>",
  "symbol": "AMD",
  "action": "ENTRY_LONG",
  "strategy": "DA_TURTLE_ADAPTIVE_TREND",
  "strategy_version": "2.4",
  "model_id": "PAPER_SHADOW_V24",
  "forward_test_start": "YYYY-MM-DD",
  "timeframe": "1D",
  "price": 0.0,
  "bar_time": "<UTC timestamp>",
  "replay_max_price": 0.0
}
```

The actual payload may contain the existing earnings, stop, liquidity and lifecycle context fields as required by the current v2.4 contract.

## Example v2.5 challenger ENTRY shape

```json
{
  "webhook_secret": "<configured in TradingView; never committed>",
  "signal_id": "<deterministic signal id>",
  "symbol": "AMD",
  "action": "ENTRY_LONG",
  "strategy": "DA_TURTLE_ADAPTIVE_TREND",
  "strategy_version": "2.5",
  "model_id": "PAPER_SHADOW_V25",
  "forward_test_start": "YYYY-MM-DD",
  "timeframe": "1D",
  "price": 0.0,
  "bar_time": "<UTC timestamp>",
  "replay_max_price": 0.0
}
```

This shape is not permission to create a v2.5 Pine implementation. The challenger rules must be frozen and reviewed separately before a source script is activated.

## Activation checklist

No ongoing shadow alerts until all are true:

- [ ] v2.4 control Pine emits the reviewed shadow fields.
- [ ] v2.5 challenger Pine exists as a versioned repository source with frozen prospective rules.
- [ ] both strategy instances are FLAT at the same start boundary.
- [ ] both emit the identical `forward_test_start`.
- [ ] every tagged ENTRY emits an explicit reviewed `replay_max_price`.
- [ ] backend `DAILY_ALPHA_SHADOW_FORWARD_START` matches the payload date.
- [ ] ingress rejects model/version/start mismatch in staging tests.
- [ ] durable ARMED replay preserves the explicit ceiling end to end.
- [ ] ordinary realtime and durable replay paper fills emit the same execution-receipt contract.
- [ ] paper ledgers remain isolated by model/account identity.
- [ ] one paper-only end-to-end staging proof completes: receive -> persist -> ARMED if required -> fresh revalidation -> PAPER fill/CANCEL/DATA_ERROR -> receipt/audit state.
- [ ] `trading_authorized=false` and `live_trading_enabled=false` verified in the final staging artifact.
- [ ] TradingView/webhook activation receives separate explicit approval.

## Safety invariants

- No source-side fallback may invent `forward_test_start` or `replay_max_price`.
- No stale market/ORATS failure may become a substitute stock/option fill.
- No orphan ADD/PARTIAL/EXIT may manufacture a paper position.
- No shadow model may read or mutate the other model's ledger state.
- No live brokerage execution path is authorized.
