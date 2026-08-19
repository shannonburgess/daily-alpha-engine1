# Daily Alpha v2.4 / v2.5 Shadow Forward-Test Pine Contract

Status: **PAPER SHADOW / NOT ACTIVATED**

This is the source-side contract for the isolated `PAPER_SHADOW_V24` control and `PAPER_SHADOW_V25` challenger. It does not enable alerts, deploy AWS production, authorize a broker route, or authorize live trading.

## Canonical ownership

The prospective shadow chain is `#185 -> #186 -> #207`:

1. `#185` — durable ARMED replay/revalidation and orphan-state reconciliation.
2. `#186` — isolated v2.4/v2.5 shadow books plus one synchronized forward-test start.
3. `#207` — explicit `replay_max_price` preservation/validation and source contract.

Do not create another shadow implementation beside this chain.

## Source status after the 2026-08-19 TradingView audit

### v2.4 CONTROL — prepared, compiled, FLAT

`tradingview/da_turtle_20_10_v2_4_shadow_control.pine` is a versioned copy of the current v2.4 strategy with only shadow-control additions:

- `model_id = PAPER_SHADOW_V24` on all lifecycle events;
- configurable `forward_test_start` on all lifecycle events;
- explicit deterministic `replay_max_price` on ENTRY;
- forward-test strategy gating so the shadow copy starts FLAT before the chosen boundary;
- paper-shadow enable toggle defaults **OFF**;
- webhook attachment defaults **OFF**;
- webhook secret defaults blank and no secret is committed.

The underlying v2.4 entry, add, harvest, failed-breakout, Turtle-exit and adaptive-trend-exit rules are preserved. The user loaded the shadow copy in TradingView, verified successful compilation, and verified the strategy report has no trades while the forward-test toggle remains OFF.

### v2.5 CHALLENGER — exact transformed source archived, compiled, FLAT

The user supplied the full current Pine source loaded in TradingView as `DA-T20/10-ARM25` on 2026-08-19. The source capture is recorded in `tradingview/v2_5_shadow_challenger_source_gate.json` with SHA-256 provenance, so the persistent-arm and structural-exit state machine was not reconstructed from screenshots.

The exact reviewed SH25 transform is archived at `tradingview/da_turtle_20_10_v2_5_shadow_challenger.pine.gz.b64` using gzip+base64. Decoding that artifact produces SHA-256 `77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718`; repository tests verify that hash and the required shadow fields. The user loaded this source as `DA-T20/10-SH25`, verified successful TradingView compilation, and verified it is FLAT with both the forward-test and webhook toggles OFF.

Verified v2.5 behavior includes:

- the price breakout itself can arm the opportunity before trend/ADX/efficiency/RSI confirmation;
- armed state is not invalidated merely because trend/ADX is not ready yet;
- armed entry requires price at/above the stored breakout and at/below the audited +1 ATR no-chase ceiling;
- 10-bar maximum arm age and -0.5 ATR invalidation;
- +1/+2 ATR adds and +3 ATR 25% harvest;
- Structural Runner Exit ON, 20-bar lookback, 1 confirmation bar;
- break-even-after-harvest OFF;
- legacy adaptive bear-flip and legacy 10-bar exits OFF;
- webhook attachment OFF and secret blank by default.

## Common forward-test boundary

Both shadow models are verified FLAT and configured to use **2026-08-19** as the synchronized forward-test boundary. Both remain disabled.

Every tagged shadow event must:

1. declare the same `forward_test_start` date;
2. match backend `DAILY_ALPHA_SHADOW_FORWARD_START` exactly;
3. be rejected if its event time predates that date.

The staging `daily-alpha-pine-processor` environment has been configured with `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19`. This must be reverified after any staging deployment before an alert is enabled.

## Model identities

- v2.4 control: `PAPER_SHADOW_V24`, strategy version `2.4`.
- v2.5 challenger: `PAPER_SHADOW_V25`, strategy version `2.5`.

No untagged event may be silently migrated into either shadow book.

## Reviewed replay no-chase rule

For delayed ENTRY replay, both models use an explicit source-side ceiling and the backend never infers or widens it.

For the v2.4 control:

`max(original confirmed signal close, breakout level + 1.0 * ATR)`

For the v2.5 challenger:

`max(original confirmed signal close, selected breakout level + selected replay ATR * 1.0)`

For an armed entry, `selected replay ATR` is the ATR stored when the breakout was armed; for a same-bar/earnings entry it is the current confirmed-bar ATR. This affects delayed replay only and does not alter the original strategy entry condition.

Every tagged shadow ENTRY carries `model_id`, `forward_test_start`, and `replay_max_price`. ADD / PARTIAL / EXIT carry `model_id` and `forward_test_start`.

## Staging-only deployment and E2E proof

The next activation gate is a **staging-only** deployment and proof. Do not enable the TradingView toggles or webhooks before this passes.

1. Build the deployment package from the canonical `#185 -> #186 -> #207` branch chain and run the repository quality gates.
2. Deploy only the Pine ingress/processor components needed by the shadow contract into AWS `us-east-2` staging. Do not deploy AWS production.
3. Verify `daily-alpha-pine-processor` reports a successful update and re-read its environment to confirm `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` survived the deployment.
4. Verify paper-only invariants before signal injection: `trading_authorized=false` and `live_trading_enabled=false`.
5. Rotate/configure the previously exposed TradingView webhook secret outside source control. Never paste it into GitHub, Pine source, PR comments, or chat.
6. Send one controlled SH24/SH25 paper signal through TradingView only after the rotated secret is configured.
7. Verify: TradingView -> ingress -> durable event -> isolated model/account routing -> ARMED when applicable -> fresh market/ORATS/risk revalidation -> PAPER fill, CANCEL, or DATA_ERROR -> persisted audit/receipt state.
8. Confirm `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` never read or mutate one another's ledger state.
9. Confirm no orphan ADD/PARTIAL/EXIT created a synthetic paper position and no stale/failed ORATS result silently substituted an instrument.
10. Only after the proof passes should ongoing shadow alerts be considered for separate explicit approval.

## Activation checklist

- [x] v2.4 control source emits model/start/ceiling fields and defaults fail-closed.
- [x] exact v2.5 TradingView source captured with provenance hash.
- [x] v2.5 shadow transform generated from the captured source without reconstructing hidden state logic.
- [x] exact SH25 transform archived in-repository with byte-level SHA-256 verification.
- [x] SH24 and SH25 compiled successfully in TradingView.
- [x] both shadow copies are FLAT on the identical 2026-08-19 boundary.
- [x] staging `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` configured before deployment.
- [x] ingress validates model/version/start and explicit replay ceiling in the canonical branch.
- [x] durable ARMED replay preserves explicit ceiling in the canonical branch.
- [x] realtime/replay receipt integration exists in canonical `#185 -> #196 -> #205` chain.
- [ ] deploy the canonical shadow-routing processor chain to staging only.
- [ ] reverify the staging forward-start value after deployment.
- [ ] rotate/configure the webhook secret outside source control.
- [ ] one real paper-only staging E2E proof passes with fresh market/ORATS/risk evidence.
- [ ] verify isolated SH24/SH25 audit receipts and live-disabled invariants.
- [ ] TradingView/webhook activation separately approved.

## Safety invariants

- No source-side fallback invents `forward_test_start` or `replay_max_price`.
- No stale market/ORATS failure becomes a substitute stock/option fill.
- No orphan ADD/PARTIAL/EXIT manufactures a paper position.
- No shadow model reads or mutates the other model's ledger state.
- `trading_authorized=false`.
- `live_trading_enabled=false`.
- No live brokerage execution path is authorized.
