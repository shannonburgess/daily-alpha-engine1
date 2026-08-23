# SH24 historical Pine/Python parity evidence V1

## Purpose

Historical parity is a source-evidence problem as well as a replay problem. The deterministic SH24
engine cannot be called historically proven from OVTLYR snapshots, reconstructed price series, the
absence of persisted Pine events, or Python defaults that were never proven to match the TradingView
strategy inputs used for the reference run.

This contract defines the minimum explicit evidence needed to compare frozen TradingView v2.4 to
the Python replay without look-ahead, retrospective inference, or silent parameter substitution.

## Required evidence

A complete historical proof contains three independent market/reference artifacts **plus one exact
Pine input manifest**. The raw UTF-8 bytes of every component are SHA-256 hashed into the locked
reference identity.

1. **Point-in-time daily market + earnings evidence**
   - one strictly chronological row per daily bar,
   - timezone-aware bar-close timestamp,
   - symbol, OHLCV, and immutable source ID,
   - explicit `earnings_state=NONE|KNOWN` on every row,
   - when `KNOWN`, the reported value and `earnings_known_at` timestamp are required,
   - `earnings_known_at` must be at or before the bar-close boundary.

2. **TradingView signal reference stream**
   - explicit ENTRY/ADD/PARTIAL/EXIT rows,
   - exact bar time, signal price, entry type, runner stage, quantity when exported, and immutable
     source ID,
   - every signal time must be present in the market evidence.

3. **TradingView bar-outcome reference stream**
   - exactly one explicit row for every market bar,
   - outcome is `SIGNAL`, `REJECTED`, or `NO_TRADE`,
   - SIGNAL rows list the ordered signal actions,
   - REJECTED rows list the exact rejection reason codes,
   - NO_TRADE rows carry neither signals nor rejection reasons,
   - the signal actions must agree exactly with the separate TradingView signal stream.

4. **Exact Pine input manifest**
   - model ID, strategy version, source blob SHA and `process_orders_on_close` identity,
   - every frozen `V24Parameters` field must be present explicitly,
   - missing fields fail closed instead of being filled with Python defaults,
   - datetime inputs must be timezone-aware,
   - `process_orders_on_close` must be exactly `true`,
   - the raw manifest bytes are hashed into the locked historical reference ID.

The explicit bar-outcome artifact is intentional: **missing Pine evidence is never interpreted as
NO_TRADE**. A zero-signal history can be proven only when the explicit bar-outcome export covers
every bar. The parameter manifest is equally intentional: matching source code is insufficient when
the TradingView input settings used for that run are unknown.

## Frozen strategy binding

The historical reference is hard-bound to:

- model: `PAPER_SHADOW_V24`
- strategy version: `2.4`
- source: `tradingview/da_turtle_20_10_v2_4.pine`
- frozen source blob: `33091e312ad3069ff7d82825b370f2a73d93107c`
- Pine semantics: `process_orders_on_close=true`
- exact exported Pine input manifest for the evidence cohort

A later source/version/input set is a separate evidence cohort. It must not overwrite or be silently
combined with v2.4 evidence.

## Comparison standard

Two complementary comparisons are retained:

- **signal parity**: ENTRY/ADD/PARTIAL/EXIT count, action, price, entry type, runner stage and
  exported quantity;
- **bar-outcome parity**: explicit SIGNAL/REJECTED/NO_TRADE state, ordered signal actions,
  rejection reasons and entry type for every bar.

A discrepancy is evidence to investigate in the Python translation or source inputs. TradingView is
not modified to make a comparison pass, and no aggregate score is allowed to hide a field-level
mismatch.

## Current evidence status

The repository currently contains the deterministic replay, strict ingestion/comparison contracts,
and exact parameter-manifest locking, but it does **not** contain the genuine point-in-time daily
OHLCV + earnings artifact, matched TradingView historical signal/bar-outcome exports, and exact Pine
input export required by this standard. Historical parity therefore remains **UNPROVEN**, not failed
and not inferred.

Forward parity is a separate gate using genuine persisted TradingView events from the frozen
SH24/SH25 runtime. Neither historical nor forward evidence can authorize PAPER or live execution.
`trading_authorized=false` and `live_trading_enabled=false` remain invariant.
