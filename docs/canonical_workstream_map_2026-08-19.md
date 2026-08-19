# Daily Alpha Canonical Workstream Map

Updated: 2026-08-19

## Purpose

Keep one canonical implementation path per objective and prevent parallel branches, automation prompts, or customer-facing outputs from drifting into competing definitions of Daily Alpha.

This map is a coordination artifact only. It does not authorize deployment, TradingView mutation, customer launch, capital deployment, or live trading.

## Repository source of truth

- **Canonical roadmap:** draft PR #141 (`agent/project-roadmap-refresh-2026-08-17`).
- **Superseded roadmap:** PR #90 — closed unmerged.
- Current `main` remains the execution/configuration source of truth for already-landed behavior. Draft PRs remain proposed changes until separately reviewed/merged.

## Paper execution / zero-trade / receipt chain

Canonical stacked path:

1. **#185** — durable `ARMED_FOR_NEXT_TRADABLE_WINDOW`, replay/revalidation, orphan lifecycle reconciliation.
2. **#196** — exact ENTRY / ADD / PARTIAL / EXIT receipts integrated into realtime and durable replay execution.
3. **#205** — durable initial-risk basis and realized-R continuity through lifecycle transitions, including the local processor/audit-store/ARMED/replay/receipt contract E2E and an explicit `evaluated_at` timestamp on every reconciled realtime/replay outcome, including non-fills.

Superseded:

- **#192** — independent receipt implementation; closed unmerged after #196/#205 became the integrated canonical chain.

Rule: do not create or merge a second execution-receipt implementation outside this chain. The local #205 E2E does not replace the still-required real staging proof with fresh market/ORATS/risk revalidation. The persisted `evaluated_at` boundary is canonical audit evidence for non-fill replay outcomes that do not have an execution receipt.

## v2.4 / v2.5 prospective shadow validation

Canonical stacked path:

- **#185** — replay/reconciliation foundation.
- **#186** — isolated `PAPER_SHADOW_V24` / `PAPER_SHADOW_V25` routing and synchronized forward-test start.
- **#207** — preserves and validates explicit `replay_max_price`, archives the exact v2.4/v2.5 shadow Pine sources, and documents the source-side contract.
- **#212** — staging-only composite of #185/#186/#196/#205/#207 for receipt-aware isolated shadow routing and the real AWS paper E2E proof. This is an integration/evidence branch, not a second implementation owner.

The source-side blocker is cleared: both versioned shadow copies are archived, compile-verified in TradingView, FLAT, configured to the common `2026-08-19` forward boundary, and still have forward-test/webhook toggles OFF. Staging `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` is configured. The remaining activation gates are staging deployment of the composite candidate, post-deploy configuration re-verification, secret rotation/configuration without disclosure, one genuine TradingView -> staging -> fresh market/ORATS/risk -> PAPER fill/CANCEL/DATA_ERROR -> persisted receipt proof, isolated V24/V25 audit evidence, and separate explicit approval before ongoing shadow alerts are enabled.

## Persistent candidate/watch visibility

- **#189** — persistent `ACTIVE_BUY` visibility plus archive-derived BUY continuity state: first-seen/first-BUY/streak/last-change and explicit ineligibility reasons.
- **#199** — persistent manual research watchlist model, seeded with NFLX.
- **#206** — staging-newsletter/manual-watch publication integration stacked on #199.

These are complementary, not duplicate: ACTIVE_BUY is model state; MANUAL_WATCH is explicit research visibility.

## Candidate alert lifecycle

- **Canonical:** #144 — current-main dry-run desired-state planner.
- **Superseded:** #102 — closed unmerged.

No real TradingView mutation is authorized by either path.

## Commercial identity / subscriptions / entitlements

- **Canonical control plane:** #145 — provider-neutral account, auth/session, tenant isolation, entitlement and billing-state controls.
- **Superseded implementation:** #91 — closed unmerged.
- **Distinct product-definition layer:** #101 — beta tiers/onboarding; retain as product scope, not a second entitlement engine.

## Performance, provenance, claims, and methodology versioning

These are separate layers and should compose rather than replace one another:

- **#140** — canonical performance calculation/methodology contract.
- **#96** — customer-facing performance-claim evidence/publication gate.
- **#150** — immutable report provenance and source-evidence identity.
- **#201** — post-publication correction/supersession/retraction state machine.
- **#204** — planned methodology release/version-governance lifecycle.

Rule: do not build a second omnibus performance/governance engine. New work must extend one of these explicit layers or document why a new boundary is required.

## Delivery, reliability, release, and launch evidence

These are distinct operational layers:

- **#100** — scheduled delivery SLO/readiness evidence.
- **#164** — recipient-level commercial email preferences, suppression, bounce/complaint and replay controls.
- **#111** — disaster recovery and incident-readiness contract.
- **#169** — commercial production release/environment/rollback architecture.
- **#172** — composite commercial-beta GO/NO-GO evidence manifest.

Rule: #172 consumes evidence from the specialized layers; it must not reimplement them.

## Security, privacy, customer data, and vendor rights

- **#104** — security/privacy assurance baseline.
- **#158** — customer-data lifecycle, acknowledgement, retention/deletion/export/reconciliation controls.
- **#160** — vendor data-rights / redistribution launch gate.

These are separate control domains. Customer-data retention or vendor-rights logic should not be duplicated inside auth, delivery, or launch-gate modules.

## Commercial positioning / product packaging

- **#108** — GTM, positioning, website information architecture and analytics planning.
- **#101** — beta product tiers and onboarding.

Neither may redefine execution logic, performance methodology, or entitlement enforcement.

## Research platform

- **#193** — Strategy Forensics / missed-R diagnostics plus deterministic research artifacts and point-in-time evidence cutoffs. It now maps canonical Pine ENTRY/ARMED/replay outcomes into immutable forensics observations using fresh replay underlying prices, receipt/evaluation timestamps, and explicit underlying stops; missing historical inputs fail closed rather than being reconstructed.
- **#209** — consolidated Factor Attribution foundation + candidate evidence adapter + horizon/regime/sector evidence reporting. It replaces closed drafts #194 and #208. Point-in-time factor snapshots carry deterministic SHA-256 snapshot identity, exact weight-set identity, validated timezone-aware timestamps, deterministic order-independent snapshot-set identity, immutable forward-return joins, largest-absolute-return exclusion diagnostics at each horizon, and dated cross-sectional rank-IC history with backward-only rolling stability summaries so pooled multi-date evidence cannot silently hide sign drift or insufficient breadth.
- Quant challengers remain disconnected research unless a separate model-governance path promotes them.

Research integration rule: #193 may consume canonical execution audit evidence from #185/#196/#205, but it remains a downstream diagnostic and must never feed an execution authorization directly. #209 may join forward outcomes by immutable snapshot identity, but realized outcomes must not silently retune production ranking weights.

## ORATS reliability

These are distinct reliability layers, not duplicate implementations:

- **#82** — workflow-level serialization for ORATS-heavy research jobs.
- **#95** — bounded retry/backoff and explicit rate-limit classification for the standard `OratsClient`; remains a draft and is separate from historical transport.
- **Merged #188** — strict historical daily/earnings transport and `fetch_orats_history()` wiring.
- **Merged #197** — strict historical option-chain / contract-snapshot transport on current `main`.

Historical duplicates/replaced foundations such as #110, #137 and #190 are closed unmerged. Issue #106's historical transport objective is completed. Future historical ORATS work must extend current `main`; future standard-client resilience should continue through #95 or explicitly supersede it before new implementation begins.

## Automation / reporting consistency rule

Every automated engineering or reporting job must reconcile against:

1. current `main` for landed behavior and configuration;
2. this canonical workstream map / PR #141 for proposed ownership and roadmap state;
3. explicitly labeled draft research for non-production hypotheses.

If an older automation instruction conflicts with current `main`, current `main` wins. If two draft PRs claim the same objective, stop parallel implementation and designate one canonical chain before adding more code. Staging integration PR #212 may compose canonical draft branches for external proof, but it must not redefine strategy/risk rules or become a parallel production implementation.

## Safety invariants

- `trading_authorized=false`
- `live_trading_enabled=false`
- no live brokerage execution
- no AWS production deployment
- no TradingView mutation/webhook enablement
- no customer launch or public performance claim
- no research challenger self-promotes into paper/live execution
