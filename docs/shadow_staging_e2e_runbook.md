# Daily Alpha Shadow Staging E2E Runbook

Status: **PAPER / STAGING ONLY — BACKEND + TRADINGVIEW TRANSPORT PROOFS PASSED; ACTUAL SH24/SH25 STRATEGY-ORIGIN PROOF STILL PENDING**

This runbook proves the canonical `#185 -> #186 -> #196 -> #205 -> #207` integration without enabling live trading or production deployment.

## Preconditions

- PR #207 source contract is green and both TradingView shadow copies are loaded, compiled and FLAT.
- `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` both use `forward_test_start=2026-08-19`.
- Both TradingView forward-test toggles are OFF.
- Both webhook toggles are OFF.
- Staging Lambda `daily-alpha-pine-processor` has `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19`.
- `trading_authorized=false` and `live_trading_enabled=false` remain mandatory.

## Stage 1 — deploy the composite candidate — PASSED 2026-08-19

The staging-only composite was deployed successfully to `us-east-2` with only:

- `daily-alpha-pine-ingress`
- `daily-alpha-pine-processor`

The deployment verified `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` before and after deployment, confirmed both isolated shadow books exist, and confirmed `trading_authorized=false` / `live_trading_enabled=false`.

Temporary branch-only deployment/test workflows used to obtain this proof were removed afterward so they cannot become a second long-term deployment path. The canonical reusable deployment workflow remains `.github/workflows/deploy-staging-lambdas.yml`.

## Stage 2 — rotate/configure webhook secret — PASSED 2026-08-19

The staging secret reference remains:

`daily-alpha/pine-webhook/staging`

The operator rotated the secret outside GitHub/chat. AWS showed the new version as `AWSCURRENT` and the prior version as `AWSPREVIOUS`. The secret value was not committed to source control or recorded in this runbook.

The GitHub staging deployment role is intentionally **not** granted `secretsmanager:GetSecretValue`; the failed temporary workflow confirmed that least-privilege boundary. Do not weaken that IAM boundary merely to automate the test.

## Stage 3A — authenticated backend ingress proof — PASSED 2026-08-19

A manual CloudShell proof used `AWSCURRENT` without printing the secret and sent a deliberately harmless v2.5 orphan `ADD` event through the real staging path:

`daily-alpha-pine-ingress -> SQS -> daily-alpha-pine-processor -> PAPER_SHADOW_V25 audit state`

Expected fail-closed result was observed:

- `disposition=STATE_MISMATCH`
- `reason=TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER`
- `paper_account_id=PAPER_SHADOW_V25`
- `paper_execution_triggered=false`
- `trading_authorized=false`
- `live_trading_enabled=false`
- both `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` remained FLAT
- terminal proof output: `BACKEND SHADOW E2E: PASS`

This proves authenticated ingress, queueing, processor persistence, model/account isolation and fail-closed lifecycle handling. It deliberately does **not** claim a paper fill or fresh ORATS/risk replay proof.

## Stage 3B — TradingView webhook transport proof — PASSED 2026-08-19

A temporary non-trading TradingView connectivity indicator emitted one controlled v2.5 `ADD` event to the real public `/pine` endpoint. The event used the rotated staging secret inside TradingView only and did not place a strategy order.

Observed result:

- terminal proof output: `TRADINGVIEW -> AWS E2E: PASS`
- `disposition=STATE_MISMATCH`
- `paper_account=PAPER_SHADOW_V25`
- `paper_execution_triggered=false`
- `live_trading_enabled=false`

The temporary alert/indicator is test-only and must not be treated as an ongoing strategy alert. This proof establishes TradingView -> API Gateway -> Pine ingress -> SQS -> processor transport/authentication and isolated V25 persistence. It does **not** prove that the actual SH24/SH25 strategy copy emitted its reviewed model/start/replay contract, and it does **not** exercise fresh ORATS/portfolio-risk execution revalidation.

## Stage 3C — actual SH24/SH25 strategy-origin paper proof — PENDING

The remaining activation gate is one controlled signal originating from the actual SH24 or SH25 TradingView copy. It must preserve the rotated secret outside chat/source control and capture evidence for this exact chain:

1. TradingView emits a tagged shadow event with `model_id`, `forward_test_start`, and, for ENTRY, `replay_max_price`.
2. Pine ingress authenticates and normalizes the event without retaining the webhook secret.
3. The processor persists the event under the model-specific paper account.
4. If outside the tradable window, the event becomes `ARMED_FOR_NEXT_TRADABLE_WINDOW` rather than a synthetic fill.
5. Replay uses fresh market/ORATS/risk context and respects the source-side replay ceiling.
6. Final state is a genuine PAPER fill, CANCEL, DATA_ERROR, or other explicit fail-closed outcome.
7. The exact execution receipt/evaluation timestamp is persisted back to the originating audit event when applicable.
8. `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25` remain isolated from one another and from the legacy `paper-staging` book.
9. Evidence shows `trading_authorized=false` and `live_trading_enabled=false`.

A local/stubbed replay test does not satisfy this gate. Stage 3A and Stage 3B prove backend/authenticated transport boundaries but do not replace the actual strategy-origin fresh ORATS/risk execution proof.

## Stage 4 — activation decision

Only after Stage 3C passes may ongoing V24/V25 shadow alerts be considered. Enabling either TradingView forward-test/webhook toggle requires separate explicit approval. No live broker route is part of this process.
