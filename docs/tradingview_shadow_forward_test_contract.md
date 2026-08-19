# Daily Alpha v2.4 / v2.5 Shadow Forward-Test Pine Contract

Status: **PAPER SHADOW / BACKEND STAGING PROOF PASSED / TRADINGVIEW-ORIGIN PROOF NOT ACTIVATED**

This is the source-side contract for the isolated `PAPER_SHADOW_V24` control and `PAPER_SHADOW_V25` challenger. It does not enable alerts, deploy AWS production, authorize a broker route, or authorize live trading.

## Canonical ownership

The prospective shadow chain is `#185 -> #186 -> #207`:

1. `#185` — durable ARMED replay/revalidation and orphan-state reconciliation.
2. `#186` — isolated v2.4/v2.5 shadow books plus one synchronized forward-test start.
3. `#207` — explicit `replay_max_price` preservation/validation and source contract.

Main-based staging composite/evidence PR #212 composes this chain with #196/#205 for external proof; it is not a second source implementation. Duplicate stacked staging PR #211 is closed unmerged.

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

The staging `daily-alpha-pine-processor` environment is configured with `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` and that value was reverified before and after the 2026-08-19 staging deployment.

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

## Staging proof status — 2026-08-19

### Completed

1. The composite candidate was deployed to **staging only** in `us-east-2`; only `daily-alpha-pine-ingress` and `daily-alpha-pine-processor` were changed.
2. `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` was verified before and after deployment.
3. `PAPER_SHADOW_V24` / `PAPER_SHADOW_V25` isolation and `trading_authorized=false` / `live_trading_enabled=false` were verified.
4. The staging secret `daily-alpha/pine-webhook/staging` was rotated outside source control/chat. AWS showed the new version as `AWSCURRENT` and the prior version as `AWSPREVIOUS`; the value is not committed or documented.
5. The GitHub staging deploy role was intentionally kept unable to read secret values; a temporary diagnostic confirmed that least-privilege boundary and the temporary secret-reading test workflows were removed rather than widening IAM.
6. A manual authenticated backend proof sent a harmless v2.5 orphan `ADD` through the real path `ingress -> SQS -> processor -> PAPER_SHADOW_V25`. The expected fail-closed `STATE_MISMATCH / TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER` was observed, no paper fill was created, both shadow books remained FLAT, and terminal output reported `BACKEND SHADOW E2E: PASS` with live trading disabled.

### Remaining

The final pre-activation gate is one **controlled TradingView-origin** SH24/SH25 shadow event after the rotated secret is configured directly in TradingView. That proof must show:

1. TradingView emits a tagged event with `model_id`, `forward_test_start`, and, for ENTRY, `replay_max_price`.
2. Pine ingress authenticates and normalizes the event without retaining the secret.
3. The processor persists the event in the correct isolated paper book.
4. If applicable, the event becomes `ARMED_FOR_NEXT_TRADABLE_WINDOW` instead of a synthetic fill.
5. Replay/execution uses fresh market/ORATS/portfolio-risk context and respects the source-side replay ceiling.
6. Final state is a genuine PAPER fill, CANCEL, DATA_ERROR, or other explicit fail-closed outcome.
7. Exact receipt/evaluation evidence is persisted when applicable.
8. V24/V25 isolation and both live-safety flags remain intact.

The successful backend orphan-ADD proof does not replace this fresh ORATS/risk execution-path proof.

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
- [x] canonical composite Pine ingress/processor deployed to staging only.
- [x] staging forward-start value reverified after deployment.
- [x] webhook secret rotated outside source control/chat.
- [x] authenticated backend ingress -> SQS -> processor -> isolated shadow audit proof passed with both books FLAT.
- [ ] one controlled TradingView-origin paper-only proof passes with fresh market/ORATS/risk evidence.
- [ ] verify persisted TradingView-origin SH24/SH25 audit receipt/evaluation evidence and live-disabled invariants.
- [ ] ongoing TradingView/webhook activation separately approved.

## Safety invariants

- No source-side fallback invents `forward_test_start` or `replay_max_price`.
- No stale market/ORATS failure becomes a substitute stock/option fill.
- No orphan ADD/PARTIAL/EXIT manufactures a paper position.
- No shadow model reads or mutates the other model's ledger state.
- `trading_authorized=false`.
- `live_trading_enabled=false`.
- No live brokerage execution path is authorized.
