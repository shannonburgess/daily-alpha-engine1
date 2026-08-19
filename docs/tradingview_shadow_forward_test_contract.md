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

### v2.5 CHALLENGER — exact source capture still required

The exact Pine source currently loaded in TradingView as `DA-T20/10-ARM25` is **not archived in the repository or available uploaded-file library**. The screenshots are enough to verify its inputs, but not enough to reconstruct its state-transition logic without guessing. Therefore no fabricated v2.5 source has been committed and v2.5 activation remains fail-closed.

The audited source gate is recorded in `tradingview/v2_5_shadow_challenger_source_gate.json`. The verified settings include:

- 20-bar entry / legacy 10-bar exit reference / Close confirmation;
- ATR 10, adaptive factors 2/4, efficiency lookback 20;
- ADX required, 14/14, minimum ADX **25**;
- trend-efficiency floor **0.20**;
- minimum underlying price **$25**;
- Persistent Armed Breakout ON;
- maximum armed window **10 bars**;
- maximum entry distance above breakout **1.0 ATR**;
- invalidate below breakout by **0.5 ATR**;
- runner adds at +1 ATR / +2 ATR and 25% harvest at +3 ATR;
- Structural Runner Exit ON, 20-bar lookback, 1 confirmation bar;
- break-even-after-harvest OFF;
- legacy adaptive bear-flip exit OFF;
- legacy 10-bar Turtle exit OFF;
- v2.5 webhook attachment OFF and secret blank.

The exact current TradingView Pine source must be exported/captured before adding shadow metadata. Do not infer hidden state logic from chart labels or screenshots.

## Common forward-test boundary

Both shadow models must:

1. start from a clean **FLAT** TradingView strategy state;
2. use the same declared `forward_test_start` date;
3. send that exact date on every tagged shadow event;
4. match backend `DAILY_ALPHA_SHADOW_FORWARD_START` exactly;
5. reject any event whose bar/event time predates that date.

The v2.4 shadow source defaults its proposed boundary to **2026-08-19** but keeps the entire shadow forward test disabled until explicitly enabled. The shared date is synchronization metadata, not a performance-tuning parameter. If v2.5 cannot be source-captured and configured to the same clean boundary, do not start an asymmetric comparison.

## Model identities

- v2.4 control: `PAPER_SHADOW_V24`, strategy version `2.4`.
- v2.5 challenger: `PAPER_SHADOW_V25`, strategy version `2.5`.

No untagged event may be silently migrated into either shadow book.

## Reviewed replay no-chase rule

The TradingView audit verified the v2.5 entry envelope at **1.0 ATR above the breakout**.

For the v2.4 control, the replay-only ceiling is:

`max(original confirmed signal close, breakout level + 1.0 * ATR)`

This does not change when v2.4 itself generates an entry. It only prevents an after-hours replay from buying above the reviewed +1 ATR envelope; if the original valid v2.4 signal close was already above that envelope, replay may not exceed the original signal close. This satisfies the backend requirement that `replay_max_price` cannot be below the source signal price without silently widening the strategy's entry rule.

For v2.5, the exact archived source must derive the replay ceiling from its existing armed-breakout/no-chase state using the already-audited **1.0 ATR** threshold. Do not invent variable names or a second state machine before source capture.

Every tagged shadow ENTRY must carry:

```json
{
  "model_id": "PAPER_SHADOW_V24",
  "forward_test_start": "YYYY-MM-DD",
  "replay_max_price": 0.0
}
```

`replay_max_price` must be finite, positive, and at least the original signal price. The backend never infers or widens it.

ADD / PARTIAL / EXIT events carry `model_id` and `forward_test_start`; they do not invent an ENTRY replay ceiling.

## Exact TradingView activation sequence

Do not enable ongoing alerts until all gates below are complete.

1. **Load the v2.4 control as a new copy**, using `da_turtle_20_10_v2_4_shadow_control.pine`. Do not overwrite the existing v2.4 chart instance.
2. Keep `Enable Paper Shadow Forward Test` **OFF** and `Attach v2.4 Shadow Webhook Messages` **OFF** while loading and checking the script.
3. Verify the v2.4 control inputs match the audited control values. Confirm its Strategy Tester shows no position before the intended common boundary.
4. **Capture/export the exact current `DA-T20/10-ARM25` Pine source** into the canonical #207 branch. Preserve its existing strategy logic and audited inputs before making any metadata change.
5. Add only the shadow contract to that exact v2.5 source: `PAPER_SHADOW_V25`, configurable common start, ENTRY `replay_max_price`, forward-start gating, blank secret default, webhook OFF default.
6. Set both new shadow copies to the **same** forward-test date and verify both are FLAT at the boundary. Do not use a v2.5 chart carrying a historical simulated position.
7. Configure staging `DAILY_ALPHA_SHADOW_FORWARD_START` to the identical date. This is a staging configuration change only; do not deploy production.
8. Use a rotated/configured webhook secret only at the activation step. Never commit it or paste it into source. The previously exposed value is not repeated here.
9. Run one paper-only staging proof: TradingView signal -> ingress -> durable event -> ARMED when applicable -> fresh market/ORATS/risk revalidation -> PAPER fill/CANCEL/DATA_ERROR -> exact persisted receipt/audit record.
10. Verify model/account isolation, `trading_authorized=false`, and `live_trading_enabled=false` in the resulting evidence.
11. Only after that proof passes should ongoing v2.4 CONTROL and v2.5 CHALLENGER shadow alerts be enabled with separate explicit approval.

## Activation checklist

- [x] v2.4 control source emits model/start/ceiling fields and defaults fail-closed.
- [ ] exact v2.5 TradingView source archived in the repository.
- [ ] v2.5 source emits model/start/ceiling fields and defaults fail-closed.
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
