# Daily Alpha Canonical Workstream Map

Updated: 2026-08-20

## Purpose

Keep one canonical implementation path per objective and prevent branches, scheduled control loops, staging integrations, and research outputs from drifting into competing definitions of Daily Alpha.

This map is a coordination artifact only. It does not authorize production deployment, TradingView mutation, customer launch, capital deployment, or live trading.

## Repository source of truth

1. **Current `main`** is authoritative for landed behavior and deployed/staging-compatible contracts.
2. **This map / draft PR #141** is authoritative for workstream ownership and proposed sequencing.
3. Draft research PRs are proposals only until separately reviewed and merged.
4. If an older issue/PR description conflicts with current `main`, current `main` wins.

Current `main` operational head at this reconciliation is the issue #213 read-only monitor hardening merged through **#235**. The recent canonical operational sequence is:

- **#215** — automated SH24/SH25 event/book/ARMED/receipt monitoring.
- **#223** — fail-closed processor/runtime/source-contract drift monitoring.
- **#224** — canonical actionable-universe freshness, identity, rank/count, and safety monitoring.
- **#226** — sanitized backend ingress/queue/secret-reference health without exposing secret values.
- **#227** — provisional versus final post-session zero-trade semantics.
- **#230** — serialized staging Lambda deployments so deployments cannot race one another.
- **#231** — latest staging deployment health in the same read-only control loop.
- **#232** — canonical >1.5M company-liquidity evidence monitoring.
- **#233** — restored the validated SH24/SH25 processor composition after the #220 liquidity merge temporarily replaced it with an older handler.
- **#234** — post-deployment guard that invokes the actually deployed processor and requires the canonical SH24/SH25 read-only monitor contract before staging deployment can finish green.
- **#235** — fail-closed monitor evidence-integrity checks for bounded ARMED evidence, count/list consistency, and receipt/disposition/account consistency.

Do not create a second operational monitor stack beside these landed controls.

## Issue #213 — PAPER shadow operational control

**Highest operational priority.** Normal PAPER-shadow operation must not require Shannon to repeatedly edit TradingView, run CloudShell, reconcile books, or diagnose zero-trade days manually.

### Validated active state

- SH24 CONTROL and SH25 CHALLENGER remain **PAPER SHADOW only** on TradingView 1D.
- Common forward-test boundary: `2026-08-19`.
- Isolated books: `PAPER_SHADOW_V24` and `PAPER_SHADOW_V25`.
- Active staging transport: TradingView -> staging API Gateway `/pine` -> ingress -> SQS -> processor.
- Validated TradingView configuration is frozen unless a verified defect or TradingView platform limitation requires intervention.
- `trading_authorized=false` and `live_trading_enabled=false` are invariant.

### Latest verified read-only staging evidence

The latest rolling issue #213 snapshot available at this reconciliation is timestamped `2026-08-20T07:56:46.798266+00:00` and is **premarket/provisional**, not a completed zero-trade day:

- session: `2026-08-20` ET;
- phase: `PREMARKET`;
- zero-trade status: `PROVISIONAL_SESSION_NOT_OPEN`;
- genuine SH24/SH25 strategy events: **0**;
- PAPER fills: **0**;
- currently ARMED: **0**;
- V24 open positions: **0**;
- V25 open positions: **0**;
- processor: `Active` / `Successful`;
- ingress: `Active` / `Successful`;
- deployed forward-test boundary: `2026-08-19`;
- latest staging deploy observed by the monitor: completed / success, head `0b01e9ccf3995c4d0c1e0302b5b0e02cd76b9bf9`;
- no runtime/source-contract drift was detected;
- canonical source: `OVTLYR_2026-08-19.csv`;
- canonical actionable universe: **208 symbols**;
- company-liquidity evidence: **736 eligible companies**, **1,428 filtered companies**, **0 missing valid-volume companies**;
- company rule: current 30-day average daily share volume **strictly >1,500,000 shares**;
- ETFs: separate liquidity rules;
- both live-safety flags false.

PR #235 merged after that snapshot. It changes only the read-only monitor logic; the next scheduled monitor run will additionally fail closed if ARMED evidence hits its bounded limit, if visible counts disagree with returned lists, or if an `EXECUTED_PAPER` disposition/receipt/account contract is inconsistent. No AWS runtime deployment is required for #235 because the monitor script runs from `main` in GitHub Actions.

### Exact zero-trade interpretation

- Before 09:30 ET: no-event state is provisional.
- During the regular session: no-event state is provisional.
- After 16:00 ET: if no genuine SH24/SH25 strategy-origin event reached durable AWS evidence, the monitor may report `FINAL_AT_AWS_BOUNDARY`.
- `FINAL_AT_AWS_BOUNDARY` proves only that no genuine strategy event reached AWS. It does **not** prove a TradingView condition should or should not have fired.
- If strategy events arrive but do not fill, exact persisted dispositions/reasons are the no-trade diagnosis.
- E2E/connectivity proof traffic is excluded from genuine trade diagnosis.

### Platform limitation

The connected control loop has no supported TradingView API that can read or mutate private per-alert/watchlist membership. Do not compensate by repeatedly recreating validated alerts. Detect what is technically observable from AWS/GitHub, keep SH24/SH25 frozen, and require manual TradingView work only when a verified defect cannot be resolved through supported automation.

## Issue #218 — canonical actionable company liquidity

**Landed on `main` via #220.** This is the only company-equity liquidity eligibility contract.

- Individual company stocks require current 30-day average daily share volume **strictly greater than 1,500,000 shares**.
- Exactly 1,500,000, below threshold, missing, invalid, or stale company evidence => `LIQUIDITY_FILTERED`.
- The gate applies before candidate ranking, actionable newsletter/watchlist setup surfacing, and new PAPER entry/replay eligibility.
- Scanner-origin and Pine-origin PAPER entries consume the same persisted S3 eligibility evidence.
- ETFs remain on separate liquidity/capacity rules and must not be forced through the company share-volume threshold.
- PARTIAL/EXIT management remains available if a held company later becomes sub-threshold; the gate controls new risk, not safe position management.
- Merged #232 monitors the published eligibility artifact, source-file binding, threshold integrity, filtered/eligible counts, shortlist leakage, and ETF separation.
- Merged #233 restored the validated SH24/SH25 processor composition after the liquidity merge regression.
- Merged #234 prevents a future staging deployment from finishing green if the deployed processor loses the canonical SH24/SH25 monitor/isolation contract.

### ACTIVE_BUY continuation

**#189** is the single canonical ACTIVE_BUY continuity PR and is complementary to #218, not a second liquidity implementation.

#189 now:

- keeps persistent OVTLYR BUY names visible below fresh/emerging/re-entry opportunities;
- derives first-seen, first-BUY, current-streak, observation-count, and last-meaningful-change evidence from dated immutable history;
- binds ACTIVE_BUY eligibility to the same #218 liquidity snapshot/source-file contract;
- labels filtered company names `ACTIVE_BUY_LIQUIDITY_FILTERED`;
- preserves `ETF_SEPARATE_RULES`;
- prevents liquidity-filtered ACTIVE_BUYs from consuming shortlist/ORATS capacity;
- publishes deterministic `buy_continuity.json` beside canonical shortlist/liquidity evidence.

Repository workflow **#671 passed Ruff and all tests** on the reconciled #189 head. #189 remains draft because it changes candidate-shortlist behavior; do not merge it as a major ranking/visibility change without explicit approval.

## Paper execution / zero-trade / receipt chain

Canonical stacked ownership remains:

1. **#185** — durable `ARMED_FOR_NEXT_TRADABLE_WINDOW`, replay/revalidation, orphan lifecycle reconciliation.
2. **#196** — exact ENTRY / ADD / PARTIAL / EXIT receipts integrated into realtime and durable replay execution.
3. **#205** — durable initial-risk basis, realized-R continuity, and explicit `evaluated_at` on reconciled fills and non-fills.

**#192** is superseded/closed; do not create a second receipt implementation.

The behavior from this chain is already composed into the validated staging shadow processor restored by #233. Historical stacked PRs remain audit/development lineage until they are deliberately reconciled or retired; they are not authorization to deploy another processor beside current `main`.

## v2.4 / v2.5 shadow source and staging lineage

Canonical source/evidence lineage:

- **#185** — replay/reconciliation foundation.
- **#186** — isolated V24/V25 routing and synchronized forward-test start.
- **#207** — explicit `replay_max_price`, reviewed shadow source archival, and source-side contract.
- **#212** — historical single staging integration/evidence composite for the above chain.

Duplicate staging PR **#211** remains closed unmerged.

Current `main` now contains the validated processor composition restored through #233 plus the deployment/monitor safeguards through #235. Do not treat old #212 as a parallel production owner. Before any future merge/cleanup of #185/#186/#196/#205/#207/#212, reconcile against current `main` and preserve the already-landed shadow behavior.

## Candidate visibility / manual watch

- **#189** — canonical persistent ACTIVE_BUY continuity, bound to #218 liquidity.
- **#199** — persistent manual research-watch model, seeded with NFLX.
- **#206** — staging-newsletter/manual-watch publication integration stacked on #199.
- **#144** — dry-run candidate alert desired-state planner only; mutation remains disabled.

ACTIVE_BUY, manual watch, and alert desired-state planning are distinct. Manual-watch membership cannot make a symbol actionable, and no future TradingView mutation layer is authorized without a supported API plus a separately reviewed control boundary.

## Research platform

All research paths are disconnected from execution unless separately promoted through model governance. None may override Pine, ORATS, earnings, liquidity, concentration, or portfolio-risk gates.

### Strategy Forensics — #193

Canonical missed-R/post-decision diagnostic path:

- MFE/MAE, terminal return, realized R, MFE capture, missed R;
- reason-code attribution and champion/challenger disagreement;
- immutable decision/cutoff evidence;
- canonical Pine ENTRY/ARMED/replay mapping;
- strict historical ORATS daily path evidence with provenance/hashing;
- no reconstruction of unavailable historical inputs.

Next step: accumulate genuine point-in-time decisions/outcomes; do not build a second forensics engine.

### Factor Attribution — #209

Single consolidated factor-attribution path:

- explicit factor contributions and availability coverage;
- immutable snapshot/weight identities;
- exact forward-return bindings with provenance;
- horizon/regime/sector evidence;
- largest-absolute-return outlier sensitivity;
- dated cross-sectional rank-IC and backward-only rolling stability.

Next step: accumulate genuine point-in-time factor/outcome history. Realized outcomes must not silently retune production ranking weights.

### Behavioral Change Engine — issue #219 / #221

Single canonical Behavioral Change research path:

- provider-neutral point-in-time schema;
- Google Trends alpha adapter disabled as `SOURCE_UNAVAILABLE` until approved access exists;
- YouTube Data API v3 public-data transport with injected API key, bounded calls, caching, alias/video deduplication, and metric-separated video/activity observations;
- optional Similarweb adapter when API access exists; no subscription is assumed or purchased;
- versioned company/brand/product/app/domain/technology dictionary;
- immutable raw observations, daily derived snapshots, SHA-256 manifests, and fail-closed rewrite protection;
- velocity, acceleration, abnormality/z-score, persistence, and cross-source confirmation;
- named factors `SEARCH_ACCELERATION_SCORE`, `VIDEO_ATTENTION_ACCELERATION_SCORE`, `WEB_TRAFFIC_ACCELERATION_SCORE`, `CROSS_SOURCE_CONFIRMATION`, `PERSISTENCE_SCORE`, `BEHAVIORAL_CHANGE_SCORE`, and `INFORMATION_IMBALANCE_SCORE`;
- minimum two independent complete sources before a composite Behavioral score exists;
- engagement metrics remain separate until metric-specific company baselines exist;
- `INFORMATION_IMBALANCE_SCORE` stays unavailable until independently versioned Wall Street-recognition evidence exists;
- source-ablation and cutoff-bounded lead/lag validation scaffolding;
- research-only flags hard false for trading/live authorization.

The YouTube secret/API verification path has passed without exposing the key. #221 was last reconciled to the then-current operational `main` with repository CI #645 and secured YouTube verification #27 green; subsequent #213 operational merges are authoritative and must be reconciled before any eventual Behavioral Change merge if GitHub reports drift/conflict.

Behavioral/Information Edge may change research priority only. It must not double-count OVTLYR, earnings revisions, relative strength, or sector rotation, and it cannot authorize a trade.

### AI Industrial Mobilization — issue #216 / #225

Single canonical provider-neutral research path across:

compute -> memory -> packaging -> networking/optics -> data-center infrastructure -> electrical equipment -> generation -> transmission -> materials.

It derives point-in-time capex momentum, layer bottlenecks, power scarcity, monetization-vs-capex validation, and bottleneck migration from auditable industrial evidence. Speculative AGI-timing claims are excluded. #225 is research-only and should be reconciled onto current `main` before further integration if its branch remains behind/conflicted.

## ORATS reliability

- **#82** — workflow-level serialization for ORATS-heavy research jobs.
- **#95** — bounded retry/backoff and explicit rate-limit classification for the standard `OratsClient`.
- **Merged #188** — strict historical daily/earnings transport.
- **Merged #197** — strict historical option-chain/contract-snapshot transport.

Historical transport completion does not make midpoint-only historical options promotion-grade evidence. Future work must preserve executable-side/provenance limitations.

## Sector / industry / portfolio-risk / scanner sequencing

After #213/#218 operational integrity, continue canonical work without parallel implementations:

1. ACTIVE_BUY continuity (#189, approval-gated merge);
2. Strategy Forensics (#193) evidence accumulation;
3. Factor Attribution (#209) evidence accumulation;
4. scanner/universe automation and actionable-universe integrity;
5. ORATS reliability and explicit DATA_ERROR/rate-limit handling;
6. portfolio risk/concentration/correlation evidence;
7. sector/industry rotation;
8. issue #216 AI industrial bottleneck research;
9. issue #219 Behavioral Change research;
10. commercialization readiness.

## Commercial control-plane ownership

Keep these specialized layers separate and composable:

### Identity / subscription / entitlement

- **#145** — provider-neutral account/auth/session/tenant/entitlement/billing control plane.
- **#101** — beta product tiers and onboarding scope.

### Performance / provenance / claims / methodology

- **#140** — canonical performance methodology contract.
- **#96** — customer-facing performance-claim evidence gate.
- **#150** — immutable report provenance/source evidence.
- **#201** — correction/supersession/retraction state machine.
- **#204** — methodology release/version governance.

### Delivery / reliability / release

- **#100** — scheduled delivery SLO/readiness.
- **#164** — recipient-level email preferences/suppression/bounce/complaint controls.
- **#111** — disaster recovery and incident readiness.
- **#169** — commercial production release/environment/rollback architecture.
- **#172** — composite commercial-beta GO/NO-GO evidence manifest.

### Security / privacy / data rights

- **#104** — security/privacy assurance baseline.
- **#158** — customer-data lifecycle controls.
- **#160** — vendor data-rights/redistribution gate.

### Positioning / packaging

- **#108** — GTM/positioning/site/analytics planning.
- **#101** — beta product tiers/onboarding.

Commercial beta remains NO-GO until the specialized evidence gates are satisfied. Passing repository tests is not customer-launch authorization.

## Automation / reporting consistency rule

Every automated engineering/research loop must reconcile against:

1. current `main`, including merged issue #213 controls through #235 and the merged #218 liquidity contract;
2. this canonical workstream map / PR #141;
3. the live rolling issue #213 monitor evidence for staging state;
4. explicitly labeled research branches for non-production hypotheses.

If two draft PRs claim the same objective, stop parallel implementation and designate one canonical path before adding code. If a staging integration branch conflicts with current `main`, current `main` wins and the integration branch must be reconciled or retired rather than redeployed as an alternate handler.

## Safety invariants

- `trading_authorized=false`
- `live_trading_enabled=false`
- no live brokerage execution
- no AWS production deployment
- no secret exposure
- no paid-data purchase without explicit approval
- no unapproved TradingView mutation; validated SH24/SH25 configuration remains frozen unless a verified defect/platform limitation requires intervention
- no major strategy/ranking merge without explicit approval
- no research challenger self-promotes into PAPER/live execution
- no customer launch or public performance claim without the required commercial evidence/review gates
