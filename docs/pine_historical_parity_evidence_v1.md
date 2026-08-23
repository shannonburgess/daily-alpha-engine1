# SH24 historical Pine/Python parity evidence V1

## Purpose

Historical parity is a source-evidence problem as well as a replay problem. The deterministic SH24
engine cannot be called historically proven from OVTLYR snapshots, reconstructed price series, or
the absence of persisted Pine events.

This contract defines the minimum explicit evidence needed to compare frozen TradingView v2.4 to
the Python replay without look-ahead or retrospective inference.

## Required artifacts

A complete historical reference contains three independent artifacts whose exact UTF-8 bytes are
SHA-256 hashed and retained in the reference identity.

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

The third artifact is intentional: **missing Pine evidence is never interpreted as NO_TRADE**.
A zero-signal history can be proven only when the explicit bar-outcome export covers every bar.

## Frozen strategy binding

The historical reference is hard-bound to:

- model: `PAPER_SHADOW_V24`
- strategy version: `2.4`
- source: `tradingview/da_turtle_20_10_v2_4.pine`
- frozen source blob: `33091e312ad3069ff7d82825b370f2a73d93107c`
- Pine semantics: `process_orders_on_close=true`

A later source/version is a separate evidence cohort. It must not overwrite or be silently combined
with v2.4.

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

The repository currently contains the deterministic replay and ingestion/comparison contracts, but
it does **not** contain the genuine point-in-time daily OHLCV + earnings artifact and matched
TradingView historical signal/bar-outcome exports required by this standard. Historical parity
therefore remains **UNPROVEN**, not failed and not inferred.

Forward parity is a separate gate using genuine persisted TradingView events from the frozen
SH24/SH25 runtime. Neither historical nor forward evidence can authorize PAPER or live execution.
`trading_authorized=false` and `live_trading_enabled=false` remain invariant.
