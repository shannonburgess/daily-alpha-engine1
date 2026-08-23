# Paired SH24 / SH25 Pine Evidence Capture V1

## Purpose

This contract closes the evidence-intake gap between the already-merged deterministic Python parity engines and a genuine TradingView comparison. It does **not** change SH24, SH25, TradingView, PAPER, or any execution authority.

The proof unit is one paired capture for one symbol. SH24 CONTROL and SH25 CHALLENGER must use the same point-in-time market/earnings CSV. Each book then supplies its own exact Pine input manifest, TradingView script-instance manifest, signal export, and per-bar outcome export.

## Render the capture packet

```bash
python scripts/render_pine_parity_capture_packet.py \
  --symbol DINO \
  --output /tmp/dino-paired-pine-capture.json
```

The renderer freezes the repository-side identities:

- SH24 book `PAPER_SHADOW_V24`, strategy `2.4`, source `tradingview/da_turtle_20_10_v2_4.pine`, blob `33091e312ad3069ff7d82825b370f2a73d93107c`;
- SH25 book `PAPER_SHADOW_V25`, strategy `2.5`, source `tradingview/da_turtle_20_10_v2_5_shadow_challenger.pine`, blob `2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5`;
- `process_orders_on_close=true` for both books;
- `trading_authorized=false` and `live_trading_enabled=false`.

Every Pine input field is emitted with a `null` value on purpose. The capture operator must record the actual values from the TradingView instance. Python/Pine defaults must never be substituted for missing evidence.

## Shared market / earnings CSV

Required headers:

```text
time,symbol,open,high,low,close,volume,earnings_state,earnings_actual,earnings_known_at,source_id
```

The market file is shared by CONTROL and CHALLENGER so the comparison cannot silently use different histories. Bars must be strictly chronological and timezone-aware. An earnings event may be marked `KNOWN` only when `earnings_actual` and timezone-aware `earnings_known_at` prove the value was known by that bar close; otherwise the row must use `NONE` with blank earnings fields.

## TradingView signal CSV per book

Required headers:

```text
bar_time,symbol,action,price,entry_type,runner_stage,quantity_units,source_id
```

Allowed signal actions remain exactly `ENTRY_LONG`, `ADD`, `PARTIAL`, and `EXIT`. No-trade and rejection states belong in the per-bar outcome export rather than being rewritten into synthetic signals.

## TradingView per-bar outcome CSV per book

Required headers:

```text
bar_time,symbol,outcome_kind,signal_actions,rejection_reasons,entry_type,source_id
```

Coverage must include every market bar, including explicit no-trade/rejection bars. Signal actions on each bar must agree exactly with the signal export.

## Exact Pine input manifest per book

The generated skeleton contains every dataclass field required by the frozen Python parity engine. Fill every field from the actual TradingView instance. The parser rejects missing/extra fields, invalid timestamps, model/version/source mismatches, and any `process_orders_on_close` value other than `true`.

After the manifest is finalized, compute its SHA-256 over the exact JSON bytes. The TradingView instance manifest must carry that exact digest.

## TradingView instance manifest per book

Required fields are:

```text
model_id
strategy_version
book_id
source_path
source_blob_sha
script_instance_id
chart_symbol
chart_timeframe
process_orders_on_close
parameter_manifest_sha256
export_revision
captured_at
trading_authorized
live_trading_enabled
```

The validator requires a distinct script-instance ID for SH24 and SH25, the exact frozen source identity, the requested symbol, daily timeframe (`D` or `1D`), `process_orders_on_close=true`, a hash match to the exact parameter manifest, and both authority flags false.

`script_instance_id` and `export_revision` are evidence identifiers from the actual TradingView capture process; they may not be invented from repository defaults. `captured_at` must be timezone-aware.

## Paired readiness

`assess_paired_historical_evidence_readiness` delegates each book to the already-merged historical readiness/locked-reference code and then adds the TradingView-instance binding. A paired capture ID is emitted only when:

1. both individual locked historical references are valid;
2. both exact Pine parameter manifests are valid;
3. both TradingView instance manifests are valid and bound to those parameter hashes;
4. SH24 and SH25 use distinct script instances;
5. both books share the exact same market/earnings artifact;
6. every required source/revision field is present.

Until those conditions are met, the result remains blocked and no parity claim is made.

## Authority boundary

This evidence layer is read/validate/hash only. It cannot mutate TradingView, place or route orders, alter PAPER history, promote a strategy/model, enable live trading, or authorize capital. It preserves `trading_authorized=false` and `live_trading_enabled=false` throughout.
