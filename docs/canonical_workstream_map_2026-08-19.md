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
3. **#205** — durable initial-risk basis and realized-R continuity through lifecycle transitions.

Superseded:

- **#192** — independent receipt implementation; closed unmerged after #196/#205 became the integrated canonical chain.

Rule: do not create or merge a second execution-receipt implementation outside this chain.

## v2.4 / v2.5 prospective shadow validation

Canonical stacked path:

- **#185** — replay/reconciliation foundation.
- **#186** — isolated `PAPER_SHADOW_V24` / `PAPER_SHADOW_V25` routing and synchronized forward-test start.
- **#207** — preserves and validates explicit `replay_max_price` for tagged shadow entries.

Remaining source-side blocker: prospective Pine payloads must deliberately emit the common `forward_test_start` and reviewed no-chase ceiling before any webhook activation.

## Persistent candidate/watch visibility

- **#189** — persistent `ACTIVE_BUY` visibility in the research shortlist.
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

- **#193** — Strategy Forensics / missed-R diagnostics.
- **#209** — consolidated Factor Attribution foundation + candidate evidence adapter. It replaces closed drafts #194 and #208.
- Quant challengers remain disconnected research unless a separate model-governance path promotes them.

## ORATS reliability

Current `main` includes merged strict historical daily/earnings and option-contract transport from #188 and #197. Older stacked duplicates such as #190 are closed. Any remaining ORATS work should extend current `main` behavior rather than recreate the historical transport stack.

## Automation / reporting consistency rule

Every automated engineering or reporting job must reconcile against:

1. current `main` for landed behavior and configuration;
2. this canonical workstream map / PR #141 for proposed ownership and roadmap state;
3. explicitly labeled draft research for non-production hypotheses.

If an older automation instruction conflicts with current `main`, current `main` wins. If two draft PRs claim the same objective, stop parallel implementation and designate one canonical chain before adding more code.

## Safety invariants

- `trading_authorized=false`
- `live_trading_enabled=false`
- no live brokerage execution
- no AWS production deployment
- no TradingView mutation/webhook enablement
- no customer launch or public performance claim
- no research challenger self-promotes into paper/live execution
