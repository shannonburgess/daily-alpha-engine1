# Daily Alpha v2.4 / v2.5 Shadow Forward-Test Pine Contract

Status: **PAPER SHADOW / NOT ACTIVATED**

This is the source-side contract for the isolated `PAPER_SHADOW_V24` control and `PAPER_SHADOW_V25` challenger. It does not enable alerts, deploy AWS, authorize a broker route, or authorize live trading.

## Canonical ownership

The prospective shadow chain is `#185 -> #186 -> #207`:

1. `#185` — durable ARMED replay/revalidation and orphan-state reconciliation.
2. `#186` — isolated v2.4/v2.5 shadow books plus one synchronized forward-test start.
3. `#207` — explicit `replay_max_price` preservation/validation and source contract.

Do not create another shadow implementation beside this chain.

## Source status after the 2026-08-19 TradingView audit

### v2.4 CONTROL — source prepared

`tradingview/da_turtle_20_10_v2_4_shadow_control.pine` is a versioned copy of the current v2.4 strategy with only shadow-control additions:

- `model_id = PAPER_SHADOW_V24` on all lifecycle events;
- configurable `forward_test_start` on all lifecycle events;
- explicit deterministic `replay_max_price` on ENTRY;
- forward-test strategy gating so the shadow copy starts FLAT before the chosen boundary;
- paper-shadow enable toggle defaults **OFF**;
- webhook attachment defaults **OFF**;
- webhook secret defaults blank and no secret is committed.

The underlying v2.4 entry, add, harvest, failed-breakout, Turtle-exit and adaptive-trend-exit rules are preserved.

### v2.5 CHALLENGER — exact source captured

The user supplied the full current Pine source loaded in TradingView as `DA-T20/10-ARM25` on 2026-08-19. The source capture is recorded in `tradingview/v2_5_shadow_challenger_source_gate.json` with SHA-256 provenance, so the persistent-arm and structural-exit state machine no longer needs to be reconstructed from screenshots.

Verified source behavior includes:

- the price breakout itself can arm the opportunity before trend/ADX/efficiency/RSI confirmation;
- armed state is not invalidated merely because trend/ADX is not ready yet;
- armed entry requires price at/above the stored breakout and at/below the audited +1 ATR no-chase ceiling;
- 10-bar maximum arm age and -0.5 ATR invalidation;
- +1/+2 ATR adds and +3 ATR 25% harvest;
- Structural Runner Exit ON, 20-bar lookback, 1 confirmation bar;
- break-even-after-harvest OFF;
- legacy adaptive bear-flip and legacy 10-bar exits OFF;
- webhook attachment OFF and secret blank in the supplied v2.5 source.

A transformed v2.5 shadow challenger has been generated from that captured source by adding only the common forward-test boundary plus `forward_test_start` and ENTRY `replay_max_price` metadata. It remains **NOT ACTIVATED** until the transformed source is archived/reviewed and successfully compiled in TradingView.

## Common forward-test boundary

Both shadow models must:

1. start from a clean **FLAT** TradingView strategy state;
2. use the same declared `forward_test_start` date;
3. send that exact date on every tagged shadow event;
4. match backend `DAILY_ALPHA_SHADOW_FORWARD_START` exactly;
5. reject any event whose bar/event time predates that date.

The shadow sources propose **2026-08-19** as the common boundary but keep the forward test disabled until explicitly enabled. The date is synchronization metadata, not a performance-tuning parameter.

## Model identities

- v2.4 control: `PAPER_SHADOW_V24`, strategy version `2.4`.
- v2.5 challenger: `PAPER_SHADOW_V25`, strategy version `2.5`.

No untagged event may be silently migrated into either shadow book.

## Reviewed replay no-chase rule

For delayed ENTRY replay, both models use an explicit source-side ceiling and the backend never infers or widens it.

For the v2.4 control:

`max(original confirmed signal close, breakout level + 1.0 * ATR)`

For the v2.5 challenger, the ceiling preserves the captured armed-breakout rule:

`max(original confirmed signal close, selected breakout level + selected replay ATR * 1.0)`

For an armed entry, `selected replay ATR` is the ATR stored when the breakout was armed; for a same-bar/earnings entry it is the current confirmed-bar ATR. This affects delayed replay only and does not alter the original strategy entry condition.

Every tagged shadow ENTRY carries `model_id`, `forward_test_start`, and `replay_max_price`. ADD / PARTIAL / EXIT carry `model_id` and `forward_test_start`.

## Exact TradingView activation sequence

Do not enable ongoing alerts until all gates below are complete.

1. Load the v2.4 control as a **new copy**. Do not overwrite the existing v2.4 chart instance.
2. Keep `Enable Paper Shadow Forward Test` **OFF** and `Attach v2.4 Shadow Webhook Messages` **OFF** while loading and checking the script.
3. Load the generated v2.5 shadow challenger as a **new copy**. Do not overwrite `DA-T20/10-ARM25`.
4. Keep `Enable Paper Shadow Forward Test` **OFF** and v2.5 webhook attachment **OFF** while compiling and verifying the audited inputs.
5. Set both new shadow copies to the **same** forward-test date and verify both are FLAT at the boundary.
6. Configure staging `DAILY_ALPHA_SHADOW_FORWARD_START` to the identical date. This is a staging configuration change only; do not deploy production.
7. Rotate/configure the previously exposed webhook secret only at activation. Never commit or paste it into source.
8. Run one paper-only staging proof: TradingView signal -> ingress -> durable event -> ARMED when applicable -> fresh market/ORATS/risk revalidation -> PAPER fill/CANCEL/DATA_ERROR -> exact persisted receipt/audit record.
9. Verify model/account isolation, `trading_authorized=false`, and `live_trading_enabled=false` in the resulting evidence.
10. Only after that proof passes should ongoing v2.4 CONTROL and v2.5 CHALLENGER shadow alerts be enabled with separate explicit approval.

## Activation checklist

- [x] v2.4 control source emits model/start/ceiling fields and defaults fail-closed.
- [x] exact v2.5 TradingView source captured with provenance hash.
- [x] v2.5 shadow transform generated from the captured source without reconstructing hidden state logic.
- [ ] v2.5 transformed source archived/reviewed and compiled successfully in TradingView.
- [ ] both shadow copies start FLAT on the identical boundary.
- [ ] backend `DAILY_ALPHA_SHADOW_FORWARD_START` matches the payload date.
- [x] ingress validates model/version/start and explicit replay ceiling in the canonical branch.
- [x] durable ARMED replay preserves explicit ceiling in the canonical branch.
- [x] realtime/replay receipt integration exists in canonical #185 -> #196 -> #205 chain.
- [ ] one real paper-only staging E2E proof passes with fresh market/ORATS/risk evidence.
- [ ] TradingView/webhook activation separately approved.

## Safety invariants

- No source-side fallback invents `forward_test_start` or `replay_max_price`.
- No stale market/ORATS failure becomes a substitute stock/option fill.
- No orphan ADD/PARTIAL/EXIT manufactures a paper position.
- No shadow model reads or mutates the other model's ledger state.
- `trading_authorized=false`.
- `live_trading_enabled=false`.
- No live brokerage execution path is authorized.
