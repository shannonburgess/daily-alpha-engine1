# Daily Alpha Canonical Workstream Map

Updated: 2026-08-20

## Purpose

Keep one canonical implementation path per objective and prevent parallel branches, automation prompts, or customer-facing outputs from drifting into competing definitions of Daily Alpha.

This map is a coordination artifact only. It does not authorize deployment, TradingView mutation, customer launch, capital deployment, or live trading.

## Repository source of truth

- **Canonical roadmap:** draft PR #141 (`agent/project-roadmap-refresh-2026-08-17`).
- **Superseded roadmap:** PR #90 — closed unmerged.
- Current `main` remains the execution/configuration source of truth for already-landed behavior. Draft PRs remain proposed changes until separately reviewed/merged.
- **Merged #215** is the landed read-only SH24/SH25 paper-shadow event/book/receipt monitor for issue #213.
- **Merged #223** adds fail-closed staging processor/runtime/source-contract drift monitoring.
- **Merged #224** adds fail-closed canonical actionable-universe freshness, identity, rank/count and safety monitoring using the same rolling issue #213 status.
- **Merged #226** adds sanitized fail-closed backend-ingress runtime/configuration health without exposing secrets or widening monitoring IAM.
- **Merged #227** distinguishes provisional premarket/in-session no-event evidence from final post-session zero-trade evidence at the AWS boundary.

## Paper execution / zero-trade / receipt chain

Canonical stacked path:

1. **#185** — durable `ARMED_FOR_NEXT_TRADABLE_WINDOW`, replay/revalidation, orphan lifecycle reconciliation.
2. **#196** — exact ENTRY / ADD / PARTIAL / EXIT receipts integrated into realtime and durable replay execution.
3. **#205** — durable initial-risk basis and realized-R continuity through lifecycle transitions, including the local processor/audit-store/ARMED/replay/receipt contract E2E and an explicit `evaluated_at` timestamp on every reconciled realtime/replay outcome, including non-fills.

Superseded:

- **#192** — independent receipt implementation; closed unmerged after #196/#205 became the integrated canonical chain.

Rule: do not create or merge a second execution-receipt implementation outside this chain. The local #205 E2E does not replace genuine prospective paper evidence with fresh market/ORATS/risk revalidation. The persisted `evaluated_at` boundary is canonical audit evidence for non-fill replay outcomes that do not have an execution receipt.

## v2.4 / v2.5 prospective shadow validation

Canonical stacked path:

- **#185** — replay/reconciliation foundation.
- **#186** — isolated `PAPER_SHADOW_V24` / `PAPER_SHADOW_V25` routing and synchronized forward-test start.
- **#207** — preserves and validates explicit `replay_max_price`, archives the exact v2.4/v2.5 shadow Pine sources, and documents the source-side contract.
- **#212** — single main-based staging composite of #185/#186/#196/#205/#207 for receipt-aware isolated shadow routing and external proof. This is an integration/evidence branch, not a second implementation owner.
- **Merged #215** — read-only operational event/book/receipt monitor for #213.
- **Merged #223** — read-only deployed runtime/source-contract drift monitor for #213.
- **Merged #224** — read-only canonical actionable-universe freshness/identity monitor for #213.
- **Merged #226** — read-only backend ingress Lambda/queue/secret-reference health monitor for #213.
- **Merged #227** — read-only session-phase/finality classifier so an in-progress no-event state is never mislabeled a final zero-trade day.

Duplicate staging PR **#211** was closed unmerged after #212 was designated canonical for the same head branch.

The source-side blocker is cleared: both versioned shadow copies are archived and compile-verified. SH24 CONTROL and SH25 CHALLENGER are active in TradingView on **1D**, use the common `2026-08-19` forward boundary, and their validated configuration is frozen unless a verified defect or TradingView platform limitation requires a change.

Verified staging evidence on 2026-08-19:

- staging `daily-alpha-pine-ingress` + `daily-alpha-pine-processor` deployment passed in `us-east-2`;
- `DAILY_ALPHA_SHADOW_FORWARD_START=2026-08-19` was verified before and after deployment;
- isolated `PAPER_SHADOW_V24` / `PAPER_SHADOW_V25` books were verified with both live-safety flags false;
- the staging webhook secret was rotated outside GitHub/chat, with the new version becoming `AWSCURRENT` and the prior version `AWSPREVIOUS`;
- the GitHub staging deployment role intentionally remains unable to read webhook secret values; do not weaken that least-privilege boundary merely for monitoring;
- a manual authenticated backend proof passed through ingress -> SQS -> processor -> isolated `PAPER_SHADOW_V25` audit state using a harmless orphan `ADD`, producing the expected `STATE_MISMATCH / TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER`, no paper fill, both shadow books FLAT, `trading_authorized=false`, and `live_trading_enabled=false`;
- a temporary TradingView connectivity proof reached the public staging path and produced the expected fail-closed V25 state mismatch;
- the staging processor exposes read-only `GET_SHADOW_MONITOR_STATE`, returning each isolated book's positions, ARMED state, recent durable events and exact execution receipts without changing execution state;
- merged #215 performs hourly weekday read-only event/book/receipt monitoring, writes 30-day evidence artifacts, and updates one rolling issue #213 status instead of requiring Shannon to run CloudShell or reconcile books manually;
- merged #223 verifies the processor remains `Active` / `Successful`, the deployed forward-test boundary remains `2026-08-19`, and genuine/ARMED model/start/replay contracts remain intact;
- merged #224 reads the latest canonical S3 shortlist, fails closed on stale/invalid rank/count/identity/safety evidence, and records a deterministic universe SHA-256 in the same issue #213 status;
- merged #226 verifies the staging Pine ingress remains `Active` / `Successful`, has a configured secret reference and ingress queue, while preserving the monitor role's intentional inability to read secret values or invoke the public ingress;
- merged #227 classifies the ET session phase and reserves `FINAL_AT_AWS_BOUNDARY` for post-16:00 ET no-event evidence only.

Latest exact automated evidence after #227 validation found:

- session phase `POST_SESSION`, session complete `true`, zero-trade status `FINAL_AT_AWS_BOUNDARY`;
- V24: 0 open positions, 0 ARMED signals, 0 genuine strategy events;
- V25: 0 open positions, 0 ARMED signals, 0 genuine strategy events;
- three stored V25 events are prior E2E/connectivity proof events (`TV-SHADOW-E2E-*`, `API-GATEWAY-SHADOW-E2E-*`, `STAGING-SHADOW-E2E-*`) and are explicitly excluded from genuine trade diagnosis;
- 0 paper fills;
- processor `Active` / `Successful`, no runtime/source-contract drift;
- ingress `Active` / `Successful`, ingress queue configured, secret reference configured, no secret value exposed;
- canonical source `OVTLYR_2026-08-19.csv`, generated `2026-08-19T22:21:15.115081+00:00`, age 5.226h at validation, 575 actionable symbols, universe SHA-256 `5b89a107c85ff2d40e19d8ed9a5135e783861af0afadbef9744ba114a516b3d2`;
- `trading_authorized=false` and `live_trading_enabled=false` with no isolation violation.

Operational monitoring is therefore active; an actual SH24/SH25 event is not a precondition for diagnosing the day. The first genuine strategy-origin event is prospective forward-test evidence. When one arrives, preserve its tagged model/start contract, fresh market/ORATS/portfolio-risk revalidation, PAPER fill/CANCEL/DATA_ERROR or other explicit fail-closed result, and exact receipt/evaluation evidence where applicable.

Monitoring limitation: there is no supported connected TradingView API in this control loop that can inspect or rewrite private per-alert/watchlist membership. Do **not** compensate by repeatedly editing/recreating validated alerts. Detect canonical universe freshness/identity plus model/start/account drift from AWS/GitHub evidence, keep the active TradingView configuration frozen, and treat absence of a genuine event as exactly that—not proof of an alert defect and not a fabricated rejection.

## Actionable company liquidity / persistent candidate visibility

- **#220** — canonical issue #218 company-equity liquidity contract. Individual companies require current 30-day average daily share volume **strictly >1,500,000 shares** before ranking, actionable newsletter/watchlist surfacing, or new PAPER entry/replay eligibility. Missing, stale, equal-to-threshold, or below-threshold company evidence fails closed as `LIQUIDITY_FILTERED`; ETFs remain on their separate liquidity/capacity path. The same persisted S3 eligibility evidence is consumed by scanner-origin and Pine-origin PAPER entries. #220 was rebased in place onto current main after #227; current-main CI #644 passed Ruff + full pytest. It remains draft/mergeable pending explicit merge/staging approval.
- **#189** — persistent `ACTIVE_BUY` visibility plus archive-derived BUY continuity state: first-seen/first-BUY/streak/last-change and explicit ineligibility reasons. Before completion, this path must consume #220's canonical liquidity eligibility rather than define a parallel volume rule.
- **#199** — persistent manual research watchlist model, seeded with NFLX.
- **#206** — staging-newsletter/manual-watch publication integration stacked on #199.

These are complementary, not duplicate: #220 owns actionable company liquidity eligibility, ACTIVE_BUY is model state, and MANUAL_WATCH is explicit research visibility. No path may bypass the canonical >1.5M company gate once #220 is approved/landed.

## Candidate alert lifecycle

- **Canonical desired-state planner:** #144 — current-main dry-run desired-state planner.
- **Operational read-only state monitors:** merged #215/#223/#224/#226/#227 — observe AWS-side SH24/SH25 state, source/runtime/transport contract and canonical universe; they never create/delete TradingView alerts.
- **Superseded:** #102 — closed unmerged.

No automatic TradingView mutation is authorized by these paths. Any future watchlist/alert mutation layer requires a supported API and a separate reviewed boundary; until then validated SH24/SH25 configuration stays frozen.

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

- **#193** — Strategy Forensics / missed-R diagnostics plus deterministic research artifacts and point-in-time evidence cutoffs. It maps canonical Pine ENTRY/ARMED/replay outcomes into immutable forensics observations using fresh replay underlying prices, receipt/evaluation timestamps, and explicit underlying stops; missing historical inputs fail closed rather than being reconstructed.
- **#209** — consolidated Factor Attribution foundation + candidate evidence adapter + horizon/regime/sector evidence reporting. It replaces closed drafts #194 and #208. Point-in-time factor snapshots carry deterministic SHA-256 snapshot identity, exact weight-set identity, validated timezone-aware timestamps, deterministic order-independent snapshot-set identity, immutable forward-return joins, largest-absolute-return exclusion diagnostics at each horizon, and dated cross-sectional rank-IC history with backward-only rolling stability summaries.
- **#221 / issue #219** — canonical Behavioral Change Engine research path. Provider-neutral Google Trends / YouTube / Similarweb contracts, versioned entity dictionary, immutable point-in-time evidence, named Behavioral factors, minimum two independent sources, YouTube public-data transport, source-ablation and lead/lag validation scaffolding. Google Trends remains `SOURCE_UNAVAILABLE` until approved alpha access; Similarweb remains optional. #221 was rebased in place onto current main; current-main CI #645 and YouTube secret/API verification #27 passed. Behavioral evidence can change research priority only and never execution authorization.
- **#225 / issue #216** — canonical AI Industrial Mobilization / bottleneck-migration research path. Provider-neutral industrial evidence contract across compute -> memory -> packaging -> networking/optics -> data-center infrastructure -> electrical equipment -> generation -> transmission -> materials, with point-in-time capex, bottleneck, power-scarcity, monetization/capex and constraint-migration factors. It explicitly excludes speculative AGI-timing signals and remains disconnected from execution.
- Quant challengers remain disconnected research unless a separate model-governance path promotes them.

Research integration rule: #193 may consume canonical execution audit evidence from #185/#196/#205, but it remains a downstream diagnostic and must never feed an execution authorization directly. #209 may join forward outcomes by immutable snapshot identity, but realized outcomes must not silently retune production ranking weights. #221 and #225 may adjust research/theme priority only; neither may bypass sector/industry rotation, OVTLYR, earnings/revisions, company liquidity, Pine, ORATS, concentration or portfolio-risk gates.

## ORATS reliability

These are distinct reliability layers, not duplicate implementations:

- **#82** — workflow-level serialization for ORATS-heavy research jobs.
- **#95** — bounded retry/backoff and explicit rate-limit classification for the standard `OratsClient`; remains a draft and is separate from historical transport.
- **Merged #188** — strict historical daily/earnings transport and `fetch_orats_history()` wiring.
- **Merged #197** — strict historical option-chain / contract-snapshot transport on current `main`.

Historical duplicates/replaced foundations such as #110, #137 and #190 are closed unmerged. Issue #106's historical transport objective is completed. Future historical ORATS work must extend current `main`; future standard-client resilience should continue through #95 or explicitly supersede it before new implementation begins.

## Automation / reporting consistency rule

Every automated engineering or reporting job must reconcile against:

1. current `main` for landed behavior and configuration, including merged #215/#223/#224/#226/#227 operational monitoring;
2. this canonical workstream map / PR #141 for proposed ownership and roadmap state;
3. explicitly labeled draft research for non-production hypotheses.

If an older automation instruction conflicts with current `main`, current `main` wins. If two draft PRs claim the same objective, stop parallel implementation and designate one canonical chain before adding more code. Staging integration PR #212 may compose canonical draft branches for external proof, but it must not redefine strategy/risk rules or become a parallel production implementation.

## Safety invariants

- `trading_authorized=false`
- `live_trading_enabled=false`
- no live brokerage execution
- no AWS production deployment
- no unapproved TradingView mutation; validated active SH24/SH25 alerts remain frozen unless a verified defect/platform limitation requires intervention
- no customer launch or public performance claim
- no research challenger self-promotes into paper/live execution
