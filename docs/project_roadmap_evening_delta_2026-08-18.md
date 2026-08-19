# Daily Alpha Roadmap Delta — 2026-08-18 Evening

This addendum records material changes since the main roadmap draft was last consolidated. It is planning/evidence only and does not authorize production, customer launch, TradingView mutation, capital deployment, or live trading.

## Technical / research delta

### Canonical v2.4 baseline
- Issue #70 is complete: the historical canonical Gap & Go baseline is aligned to the merged 70% full-entry close-location rule, with 60%-<70% preserved as `EARNINGS_GAP_GO_EARLY` research/watch only.
- No new v2.4 threshold promotion is introduced by this delta.

### Earnings EARLY
- #71 / draft PR #134 remain watch-only.
- The first current-main empirical cohort still contains only 14 qualifying events; outlier-exclusion materially reduces the apparent mean return.
- Next evidence gate remains broader point-in-time sample construction plus executable-side option history after ORATS option transport is reliable.

### Pre-Catalyst Drift
- #72 / draft PR #135 remain research-only.
- The next real evidence task is to construct and freeze a point-in-time event manifest before calculating T-20/T-15/T-10/T-5 outcomes.
- Start with issuer-originated investor/analyst days, named conferences, product/keynote events and other issuer-disclosed scheduled events; preserve first-public timestamps, revisions, cancellations/reschedules, source URL and source hash.
- Matched controls and incremental-value tests versus ordinary R2/momentum remain mandatory.

### ORATS historical reliability
- Draft PR #188 now completes the daily/earnings `fetch_orats_history()` migration to explicit bounded historical failure semantics on current `main`.
- #188 uses the documented token-authenticated `/datav2` historical route as primary for the current account entitlement, preserves separate daily/earnings source provenance, and keeps 401/403, 429, network exhaustion and malformed data fail-closed.
- Verified #188 workflows: general tests PASS, Gap & Go sensitivity PASS, earnings-gap sleeve PASS.
- Draft PR #190 is stacked on #188 and moves `backtest_options.py` historical strikes and contract-snapshot calls onto the same strict transport, with focused propagation tests.
- Older #137/#110 are reference implementations only; do not merge duplicate transport paths alongside #188/#190.
- Issue #106 now tracks the current acceptance matrix and remaining caller audit/caching work.

### Paper lifecycle reconciliation
- Draft PR #185 adds explicit reconciliation states for missed/after-hours Pine signals and orphan ADD/PARTIAL/EXIT events without manufacturing paper positions.
- A durable replay/revalidation worker and end-to-end staging proof remain required before this is considered complete.
- Draft PR #186 adds explicit v2.4/v2.5 paper-shadow routing but is stacked on #185 and must not enable alerts. Both prospective shadow books must start FLAT on the same forward-test date before any future alert enablement.
- Live trading remains disabled.

### Candidate research visibility
- Draft PR #189 keeps valid persistent `ACTIVE_BUY` names visible in the research shortlist at lower priority than fresh/emerging/re-entry/leader states. ORATS DATA_ERROR still fails closed and cannot create an execution fallback.

### Quant Challenger queue
- New #191: institutional behavior predictability / crowding-state gate.
- Motivation: NBER Working Paper 34849 (`Mimicking Finance`) documents meaningful predictability in mutual-fund manager trade direction from prior behavior.
- Daily Alpha will test only transparent, point-in-time public-holdings proxies first and must distinguish diversified predictable accumulation from concentrated synchronized crowding/unwind risk.
- It must prove incremental value beyond R2 momentum, liquidity, #93 rebalancing pressure and #139 concentration state, with explicit holdout and kill criteria.

## Commercialization delta

### Customer-facing delivery
- PR #177 is merged for the existing staging/internal Daily Alpha newsletter: it can send the exact published newsletter HTML through configured Amazon SES and can resend the latest artifact without rebuilding research.
- This is not a commercial customer-email control plane. Draft PR #164 remains the provider-neutral commercial design for entitlement/preferences/suppression, bounce/complaint handling, idempotent sends, sender-authentication evidence and recipient-level delivery audit.

### Production/release architecture
- Draft PR #169 defines research/staging/future-production separation, immutable release manifests, no cross-environment secret fallback, rollback, drift evidence and release-aware observability. No production environment is deployed.
- Draft PR #172 defines a machine-readable commercial-beta GO/NO-GO evidence package. A passing evidence package is readiness evidence only, never launch authorization.

### Identity, data, rights, evidence
- Draft PR #145 remains the current provider-neutral auth/session/subscription/entitlement control plane.
- Draft PR #158 remains the customer-data lifecycle design for acknowledgement evidence, export/deletion reconciliation, tombstones, restore behavior and privacy-minimized analytics.
- Draft PR #160 remains the vendor data-rights / redistribution launch gate; technical reproducibility does not imply redistribution rights.
- Draft PRs #140 and #150 remain the performance-methodology and immutable report-provenance foundations.

### Current commercial beta NO-GO
Commercial beta remains NO-GO until there is evidence for all launch-scope dependencies, including:
- reproducible/versioned research and performance methodology;
- immutable report/source provenance;
- authenticated tenant isolation and deny-by-default entitlements;
- billing reconciliation without storing unnecessary payment secrets;
- customer email preference/suppression and delivery evidence;
- vendor/source rights for each customer-visible surface;
- secrets/environment isolation, monitoring and incident controls;
- backup/restore and deletion/tombstone reconciliation;
- external legal/compliance review for the actual launch scope;
- terms/privacy/support/disclosure completion;
- explicit production release/rollback approval;
- live brokerage execution remaining disabled.

## Safety boundary
No major strategy/product PR is merged by this roadmap delta. No AWS production deployment, paid account/service purchase, public website, customer contact, TradingView alert mutation, research-to-paper promotion, capital deployment or live trading is authorized.