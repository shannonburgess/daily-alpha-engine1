# Daily Alpha Shadow Staging E2E Runbook

Status: **PAPER / STAGING ONLY — NOT ACTIVATED**

This runbook proves the canonical `#185 -> #186 -> #196 -> #205 -> #207` integration without enabling live trading or production deployment.

## Preconditions

- PR #207 source contract is green and both TradingView shadow copies are loaded, compiled and FLAT.
- `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` both use `forward_test_start=2026-08-19`.
- Both TradingView forward-test toggles are OFF.
- Both webhook toggles are OFF.
- Staging Lambda `daily-alpha-pine-processor` has `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19`.
- `trading_authorized=false` and `live_trading_enabled=false` remain mandatory.

## Stage 1 — deploy the composite candidate

Use the existing **Deploy Daily Alpha staging Lambdas** workflow and select branch:

`staging/shadow-e2e-integration`

On that branch the workflow is deliberately narrowed: engine/report/paper-trader deployment steps are skipped; only `daily-alpha-pine-ingress` and `daily-alpha-pine-processor` are updated. Before deployment it fails closed unless the existing processor environment contains exactly:

`DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19`

After deployment it verifies both Pine handlers, rechecks the forward-start value, invokes `LIST_SHADOW_PAPER_POSITIONS`, confirms the two isolated books exist, and asserts both live-safety flags are false. It also reruns the existing scanner fail-closed staging proof.

## Stage 2 — rotate/configure webhook secret

Rotate the previously exposed TradingView webhook secret through the existing AWS secret-management path. Do not place the value in GitHub, this runbook, screenshots, or chat.

Keep both TradingView webhook toggles OFF until the rotated secret is configured on both new shadow copies.

## Stage 3 — real paper-only proof

Use a controlled shadow signal after the synchronized boundary and capture evidence for this exact chain:

1. TradingView emits a tagged shadow event with `model_id`, `forward_test_start`, and, for ENTRY, `replay_max_price`.
2. Pine ingress authenticates and normalizes the event without retaining the webhook secret.
3. The processor persists the event under the model-specific paper account.
4. If outside the tradable window, the event becomes `ARMED_FOR_NEXT_TRADABLE_WINDOW` rather than a synthetic fill.
5. Replay uses fresh market/ORATS/risk context and respects the source-side replay ceiling.
6. Final state is a genuine PAPER fill, CANCEL, DATA_ERROR, or other explicit fail-closed outcome.
7. The exact execution receipt/evaluation timestamp is persisted back to the originating audit event when applicable.
8. `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` remain isolated from one another and from the legacy `paper-staging` book.
9. Evidence shows `trading_authorized=false` and `live_trading_enabled=false`.

A local/stubbed replay test does not satisfy this gate.

## Stage 4 — activation decision

Only after the real staging proof passes may ongoing V24/V25 shadow alerts be considered. Enabling either TradingView forward-test/webhook toggle requires separate explicit approval. No live broker route is part of this process.
