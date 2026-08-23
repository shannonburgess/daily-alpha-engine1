# AWS-native TradingView parity migration

Status: **STAGING-PROVEN FOUNDATION / REPO-ONLY PARITY IMPLEMENTATION IN PROGRESS**

The AWS staging data-plane foundation earned `STAGING_PROVEN` on main
`dc74fb1b432417bb98ce8881d816ee4e03403b16` through canonical workflow run
`32635126967`: CloudFormation is `CREATE_COMPLETE`, the exact deployed inventory is 37
resources, S3 controls/policy passed, both DynamoDB tables have PITR enabled, and zero
activation resources exist.

This document defines the next migration boundary. It does not deploy strategy compute, mutate
TradingView, create a broker route, enable live trading, or authorize capital.

## Current integration baseline

Authoritative `main` is now `e8a14a716d2eecdb79427250ea5861b5ea681c69`, which adds the
merged V1 prospect opportunity-board launch contract and the research-only point-in-time
model-training/walk-forward framework. Those changes are independent of SH24/SH25 strategy
semantics. This parity branch must continue to validate against that current main without
absorbing product-presentation or adaptive-model logic into the frozen control strategy.

The latest complete deployed forward-monitor evidence remains the issue #213 staging receipt
from `9fd6affcbdd7914ff611b029103c95794c7ed3bb`; later main changes are repo/product research
contracts and do not constitute a new parity-runtime deployment receipt.

## Frozen source authority

### SH24 CONTROL

- model: `PAPER_SHADOW_V24`
- strategy version: `2.4`
- canonical current-main source: `tradingview/da_turtle_20_10_v2_4.pine`
- Git blob SHA: `33091e312ad3069ff7d82825b370f2a73d93107c`
- Pine execution semantics: `process_orders_on_close=true`, `calc_on_every_tick=false`,
  `calc_on_order_fills=false`

The first server-native module is `daily_alpha.pine_v24_parity`. It is a pure deterministic
replay of the frozen source state machine and emits bar-level indicator/state diagnostics,
ENTRY/ADD/PARTIAL/EXIT events, and explicit no-trade/rejection lineage. Orders generated on a
confirmed bar are applied to the simulated model state at that bar's close, matching the frozen
Pine close-processing contract.

### SH25 CHALLENGER

The exact reviewed SH25 source was not reconstructed from screenshots. Historical PR #207
preserves the audited source lineage:

- model: `PAPER_SHADOW_V25`
- strategy version: `2.5`
- archived source SHA-256:
  `77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718`
- reviewed PR head containing the plain-text challenger source:
  `b2a214c6b7a689453df5de7bb870c352456ebe8c`
- audited defaults: ADX 25, persistent armed breakout enabled, 10-bar arm, +1 ATR no-chase
  ceiling, -0.5 ATR invalidation, +1/+2 ATR runner adds, +3 ATR 25% harvest, structural runner
  exit 20/1, break-even-after-harvest disabled, legacy adaptive bear-flip and legacy 10-bar
  exits disabled

The SH25 Python engine must be translated from that exact frozen source and validated separately.
No SH24 rule is silently substituted for a missing SH25 rule.

## Parity gates

A server-native model cannot replace TradingView evidence merely because unit tests pass. The
migration advances through four evidence levels:

1. **Source-contract parity** — frozen parameters, indicator definitions, state transitions,
   close-fill timing and event payload semantics are represented explicitly.
2. **Fixture parity** — deterministic synthetic fixtures prove ENTRY, rejection, runner adds,
   harvest and exits without cross-book contamination.
3. **Historical parity** — point-in-time daily bars and earnings-event evidence are replayed
   through both Pine reference outputs and Python. Differences are recorded, not tuned away.
4. **Forward shadow parity** — the Python result is compared with genuine SH24/SH25 TradingView
   events while TradingView remains frozen. Only sustained evidence can support a later source-of-
   truth decision.

Parity reports must preserve model identity, security, bar close time, action, entry type,
runner stage, signal/model price, stop, rejection reason, and exact source/version lineage.

## Book and safety boundary

- SH24 CONTROL and SH25 CHALLENGER remain separate books.
- New PAPER positions remain STOCK/shares only.
- Confirmed model signal price remains the PAPER model-validation price; it is not a brokerage
  fill claim.
- ORATS/options are research-only and nonblocking for new stock PAPER entries.
- TradingView is not modified by this migration.
- No production AWS or broker route is introduced.
- `trading_authorized=false`.
- `live_trading_enabled=false`.
