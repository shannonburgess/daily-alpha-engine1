# Pine parity evidence readiness

## Purpose

Parity proof is blocked when required source artifacts do not exist, are incomplete, or cannot be tied
to the historical decision boundary. That state must be machine-readable rather than described only in
free-form notes.

The SH24 evidence-readiness layer inventories the exact inputs required by the existing locked replay
and historical-reference contracts. **Readiness is not parity.** A readiness result can only say that the
required evidence is present and valid enough to hand to the locked evaluator; the evaluator must still
run the deterministic Python strategy and compare it with TradingView.

## Forward SH24 readiness

A forward evidence check begins from the trusted, complete staging deployment receipt and therefore
preserves the actual persisted TradingView reference set. Explicitly registered E2E events remain audit
history but are excluded from genuine forward-reference candidates by the existing exact-ID partition.

The readiness assessment requires:

- at least one genuine persisted SH24 TradingView event for the requested symbol;
- point-in-time OHLCV plus explicit earnings-known-at evidence containing every genuine event bar;
- an explicit market source identity and immutable source revision;
- the complete v2.4 Pine parameter manifest, bound to the frozen source blob and
  `process_orders_on_close=true`;
- an explicit Python parity-engine revision.

Missing evidence is reported with stable blocker codes. Supplied evidence is parsed using the same
strict market/earnings and Pine-parameter contracts used by the locked replay. Invalid evidence is not
treated as missing and is not repaired with defaults.

For the current DINO forward event, the persisted TradingView source event is already proven by the
staging receipt. That does **not** supply the missing point-in-time DINO replay cohort or the exact Pine
input manifest used by TradingView for that event.

## Historical SH24 readiness

Historical proof requires four independent artifact classes:

1. point-in-time daily market + earnings-known-at evidence;
2. TradingView ENTRY/ADD/PARTIAL/EXIT reference export;
3. an explicit TradingView SIGNAL/REJECTED/NO_TRADE row for every market bar;
4. the complete exact v2.4 Pine input manifest with `process_orders_on_close=true`.

It also requires explicit source/revision identities for each evidence stream. Only a bundle that can
successfully build the existing `LockedHistoricalV24Reference` is classified ready.

## Non-substitution rules

The readiness layer never:

- treats absent Pine events as NO_TRADE;
- fills missing Pine settings from Python defaults;
- substitutes OVTLYR snapshots for point-in-time OHLCV/earnings evidence;
- reconstructs a favorable market series from later data;
- changes TradingView to make Python agree;
- treats downstream PAPER disposition as source-signal truth;
- authorizes PAPER or live trading.

`trading_authorized=false` and `live_trading_enabled=false` remain invariant.

## Operational use

Issue #213 and future automated parity monitors can consume the stable blocker codes to distinguish
an actual implementation discrepancy from a missing-evidence condition. This allows the system to say
exactly why historical or forward parity cannot yet be evaluated without weakening the proof standard.
