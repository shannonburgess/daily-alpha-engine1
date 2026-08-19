# Daily Alpha Roadmap Status Delta — 2026-08-18 Evening

This file is an additive status delta for `docs/project_roadmap.md`. It records changes that occurred after the original 2026-08-17 roadmap snapshot without promoting research into paper/live execution.

## Technical backlog

### v2.4 baseline
- Canonical full Earnings Gap & Go remains 70% close-location; 60%-<70% remains `EARNINGS_GAP_GO_EARLY` research/watch only.
- ADX floor remains 17.
- No threshold change is authorized by this status update.

### ORATS historical reliability
- PR #188 merged to `main`: legacy `fetch_orats_history()` no longer uses the broad generic RuntimeError compatibility fallback.
- Historical daily and earnings calls now use explicit RATE_LIMITED / AUTH / transient-network / HTTP / malformed-data classification with endpoint provenance.
- Current-account historical access uses the documented token-authenticated `datav2` path as primary; 401/403/429/network/malformed failures are not reinterpreted as compatibility failures.
- PR #197 also merged to `main`: historical option-strikes and option-contract callers now use the same strict transport. Both the general test suite and the historical-options workflow passed before merge.
- Stacked PR #190 was closed unmerged as superseded.
- Required invariant: a failed ORATS request must never become `NO_QUALIFIED_OPTION` or synthetic missing data.
- Issue #106 remains open only for broader follow-up: audit any additional historical callers, safe caching/batching, end-to-end state propagation, and executable-side quote/cost/roll/expiry evidence before any option-strategy promotion.

### Earnings EARLY
- Draft PR #134 remains watch-only.
- Current fixed underlying cohort remains 14 qualifying events across the 61-name screen through 2026-07-31.
- The 20-day result is suggestive but materially outlier-sensitive; sample size is still insufficient for promotion.
- `docs/earnings_early_universe_manifest_spec.md` now defines a frozen point-in-time universe/eligibility manifest so cohort expansion does not depend on present-day survivors; CI and the EARLY research workflow are green.
- Next work is cohort expansion under frozen 60%/70% boundaries, not threshold tuning.

### Pre-Catalyst Drift
- Draft PR #135 remains research-only.
- Point-in-time manifest construction, source hashing, revision/cancellation history and matched-control requirements are explicit.
- `docs/pre_catalyst_official_source_acquisition_spec.md` now defines SEC EDGAR acceptance/accession evidence, issuer IR sources and official event-organizer evidence as the strict acquisition hierarchy; CI is green.
- No return test should begin until the event manifest is frozen/versioned; insufficient point-in-time N is a valid kill/defer outcome.

## Quant Research Challenger queue

### New challenger #198 — short-dated option intensity / gamma-noise regime
- Test whether elevated <=7 DTE option activity changes R2 continuation, MAE/slippage or stock-vs-option expression.
- Do not assume dealer-gamma direction from public OI.
- Control for realized volatility, liquidity, earnings/event proximity, ADX/efficiency, recent returns, sector and broad regime.
- Kill if it only rediscovers volatility/event risk or has unstable sign without a reproducible state variable.

### New platform research foundations
- Draft PR #193 adds research-only Strategy Forensics / missed-R diagnostics so WAIT/NO_TRADE/early-exit opportunity cost can be measured rather than debated from anecdotes.
- Draft PR #194 adds a research-only Factor Attribution foundation with explicit factor contributions, IC/hit-rate evidence and ablation records. No ranking weight can change from these modules without later point-in-time walk-forward evidence.

## Paper/staging reliability context
- Autonomous paper execution remains paper-only with live trading disabled.
- Draft PR #185 addresses after-hours/missed-signal reconciliation and orphan runner-state handling.
- Draft PR #186 adds isolated v2.4/v2.5 shadow-routing architecture; it remains paper-only and requires synchronized flat forward-test start before any alert activation.
- Draft PR #192 adds exact paper execution receipts; it records actual paper fill identity/quantity/price and does not change authorization logic.
- No TradingView mutation or live brokerage path is authorized by this roadmap delta.

## Commercialization roadmap

Commercial beta remains NO-GO. Current safe/reversible work is concentrated in:
- #145 authentication/session/subscription/entitlement/billing control plane;
- #140 canonical performance methodology and basis separation;
- #150 immutable report provenance;
- #158 customer-data lifecycle/export/deletion/tombstone controls;
- #160 vendor data-rights/redistribution gate;
- #164 customer email preference/suppression/bounce/complaint controls;
- #169 research/staging/future-production release architecture;
- #172 machine-readable commercial beta launch evidence gate;
- #111 disaster recovery / incident readiness;
- #108 positioning/website/pricing hypotheses;
- #144 dry-run candidate/alert desired-state planning;
- #200 / draft PR #201 customer-visible research correction/supersession/retraction controls. The draft keeps original report artifacts immutable, blocks non-current evidence/delivery replay, requires replacement-report lineage and remains disconnected from actual customer communication.

### Commercial beta NO-GO invariants
Do not launch until evidence exists for all planned launch-scope dependencies: reproducible research/provenance; versioned performance methodology and claims governance; authentication/tenant isolation/entitlements; billing reconciliation; preference/suppression-safe delivery; sender-authentication readiness; data-rights approval for each customer-visible surface; security/privacy/customer-data controls; restore/incident drills; report correction/retraction handling; terms/privacy/support/disclosure requirements; applicable external legal/compliance review; production release/rollback evidence; and an explicit user-approved launch decision.

## Immediate safe next sequence
1. Audit any remaining historical ORATS callers and keep transport failures distinct from missing options; do not weaken the now-merged strict transport.
2. Expand Earnings EARLY N using the frozen point-in-time universe approach without changing thresholds.
3. Build/freeze the Pre-Catalyst point-in-time event manifest before return analysis.
4. Integrate immutable candidate/decision history into Strategy Forensics and Factor Attribution research modules.
5. Continue commercial control-plane specs/tests, including report correction lineage, without activating providers, billing, customer email, website publication or AWS production.

## Safety boundary
No AWS production deployment, paid-service activation, customer outreach, public website, TradingView alert mutation, research-rule promotion, capital deployment, legal/compliance claim or live-trading authorization is introduced by this status delta.
