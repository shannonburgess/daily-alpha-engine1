# Daily Alpha Project Roadmap

Updated: 2026-08-17 late evening, Pacific Time

## Current operating boundary

Daily Alpha remains a research and **paper-trading** platform. Canonical v2.4 uses the corrected 70% full Earnings Gap & Go threshold and a 60%-<70% `EARNINGS_GAP_GO_EARLY` research/watch band. The canonical ADX entry floor is 17. Qualifying paper ENTRY and ADD actions no longer require a human approval step: lifecycle-aware sizing now permits autonomous paper execution within the existing hard portfolio-risk controls, with winner-only ATR-confirmed adds and no averaging down. Missing/unknown lifecycle metadata falls back to the smallest starter allocation rather than vetoing an otherwise valid paper signal, and Extended Leaders may take a reduced starter rather than being categorically blocked. Live brokerage execution remains disabled.

The current production-research split is intentional: stable v2.4 paper behavior stays distinct from new R2 Long-Runner, portfolio-overlay, options, sector-ETF, SGOV, downside-risk and commercialization ideas, which remain disconnected research/draft work unless separately approved.

## Workstream A — Paper-trading and staging readiness

### Completed / landed
- v2.4 historical baseline aligned to 70% Gap & Go; PR #77 merged.
- server-side Top-20 + open-position execution-universe scanner; PR #124 merged.
- next-regular-session staging/execution lifecycle; PR #126 merged.
- ADX17 paper entry floor and hard risk gate; PR #130 merged.
- gated automatic deployment of paper-runtime changes to staging; PR #131 merged.
- staging deployment rehearsal gate; PR #132 merged.
- autonomous lifecycle sizing and winner-only paper pyramiding; PR #147 merged.
- valid paper signals no longer fail solely because lifecycle metadata is missing/unknown; smallest starter fallback in PR #148 merged.
- Extended Leaders are no longer categorically blocked; qualifying fresh signals use a reduced starter allocation under PR #149.

### Remaining evidence gates
1. Confirm scheduled close scan produces staged actions only, with zero after-hours paper fills.
2. Confirm next-session revalidation uses fresh market/ORATS data and either executes a qualifying paper action or records CANCEL / DATA_ERROR.
3. Confirm retry path remains fail-closed for persistent data errors.
4. Reconcile paper ledger, runner state, lifecycle sizing, intended versus executed instrument, fees/slippage and duplicate/idempotency behavior.
5. Persist and enforce sector/correlation exposure in the execution ledger rather than relying only on upstream classification.
6. Preserve live-trading lockout and require a separate explicit approval path for any future actual-capital execution.

## Workstream B — Active research backlog

### Earnings EARLY
Track: #71 / draft PR #134.

Current state:
- refreshed on current `main` after the canonical baseline correction;
- `NO_ENTRY`, 25% starter-only and 25%→50% T+1/T+2 confirmation scenarios remain research-only;
- first empirical screen across 61 requested liquid names produced only 14 qualifying EARLY events from 2022 through 2026-07-31;
- 20-day mean return was +3.60% and median +1.12%; excluding the best event reduced the mean to +2.02%, leaving insufficient sample size for promotion;
- 40-day results were right-tail unstable, reinforcing the need for more events rather than a broader holding-period claim.

Promotion gate: no EARLY starter enters paper/live until a broader point-in-time cohort proves incremental value without depending on MRVL or another single outlier.

### Pre-Catalyst Drift
Track: #72 / draft PR #135.

Current state:
- refreshed on current `main`;
- hard `event_known_date` boundary prevents lookahead;
- point-in-time catalyst manifest requires timezone-aware public-known/first-seen timestamps, source URL and source hash;
- `PRE_CATALYST_WATCH` / `PRE_CATALYST_RUN` remain descriptive research states only;
- matched-control and incremental-value tests are required to prove benefit beyond ordinary momentum/R2 trend.

Promotion gate: no scheduled non-earnings catalyst becomes a trade authorization without a frozen point-in-time event manifest, sufficient N, matched-control evidence and walk-forward stability.

### ORATS reliability
Track: #75 / #106 / PR #82 / PR #95 / draft PR #137.

Current state:
- heavy research workflows are serialized;
- standard ORATS client has bounded 429/transient retry and distinct rate-limit classification;
- refreshed historical transport distinguishes RATE_LIMITED / AUTH / REQUEST / HTTP / malformed-data failures;
- strict compatibility-route helper allows a legacy-route fallback only on explicit endpoint incompatibility, never on 429, 401/403, network exhaustion, malformed data or ordinary bad requests;
- draft PR #137 contains a strict historical daily/earnings fetch adapter with tests proving RATE_LIMITED cannot be reinterpreted as compatibility fallback or missing data.

Remaining:
- switch legacy `fetch_orats_history()` in `backtest.py` to the new daily/earnings adapter and preserve route/source provenance;
- update historical option callers after reconciling older stacked PR #110;
- add safe per-run caching/batching where it materially reduces duplicate historical requests;
- preserve `DATA_ERROR` / `RATE_LIMITED` / `NO_QUALIFIED_OPTION` as distinct states end-to-end.

A new concrete entitlement limitation surfaced in downside research: the current ORATS account returns HTTP 403 for historical SGOV dividend data. Research must not silently substitute price-only SGOV; reserve studies use a clearly labeled Treasury-carry approximation until distribution-adjusted/broker-grade SGOV total return is available.

### R2 Long-Runner research
Current leading research hypothesis:
- 20-day fresh breakout;
- ADX >=17 and rising;
- efficiency >=0.20;
- RSI <=80;
- bullish adaptive trend / mature trend confirmation;
- quality close filter in the current champion;
- scale into strength at +1 ATR and +2 ATR;
- no automatic +3 ATR harvest in the current leading model;
- primary 55-day trend exit;
- hard close-based risk cap preserving the canonical Daily Alpha 1R definition.

Current result is promising but still research-only. The weak 2025 validation regime remains the key falsification/stability problem; do not promote by optimizing 2025 thresholds after the fact.

### Portfolio construction / downside research
Track: PR #127, #114, #115, #133, #142 / draft PR #143, draft PR #152, #154.

Required independent attribution tests:
- R2 shares-only baseline;
- Treasury/SGOV reserve sleeve for unused investable capital, retaining an operational cash buffer;
- stock + long-dated option accelerator under one combined risk budget;
- selective 2x / 3x sector proxy when sector leadership is strong but no individual stock qualifies;
- volatility/regime-aware risk-budget reduction;
- dynamic SPY/QQQ beta hedge;
- small index-put tail hedge / put-spread / collar cost challenger once executable historical option marks are reliable;
- shrinkage-covariance marginal-risk-contribution governor.

#### Phase-1 downside-overlay result — draft PR #152
First completed 2022-01-03 through 2026-07-31 portfolio run on 60 liquid U.S. equities, before the reserve total-return correction:
- R2 core/cash: CAGR 11.11%, annualized volatility 15.05%, Sharpe 0.738, Sortino 1.022, max drawdown 22.07%, Calmar 0.503, worst month -9.22%, beta 0.716.
- dynamic SPY beta hedge: CAGR 10.20%, volatility 12.55%, Sharpe 0.812, Sortino 1.135, max drawdown 19.03%, Calmar 0.536, worst month -6.76%, beta 0.450.
- hard drawdown throttle: CAGR 7.59%, volatility 10.59%, max drawdown 15.03%, Calmar 0.505 and a 498-trading-day recovery; current thresholds sacrifice too much return/recovery for promotion.
- combined throttle + beta hedge: max drawdown 13.11% and Calmar 0.568, but CAGR falls to 7.44%; stronger protection, excessive return penalty.

Leading phase-1 hypothesis: **dynamic beta hedging currently dominates the hard drawdown throttle on return preservation and improves Sharpe/Sortino, worst month, beta and max drawdown.** This is not promotion-grade yet and must survive reserve-accounting correction, universe cleanup, costs and further out-of-sample testing.

The initial SGOV implementation used price-only OHLC and therefore understated reserve economics. The branch is being corrected to use a fail-closed FRED DGS3MO 3-month Treasury carry proxy less the current SGOV expense ratio, with source hashing. It remains an approximation, not exact SGOV shareholder total return.

Tail puts remain intentionally excluded from phase 1 because credible option insurance requires timestamp-aligned executable-side historical quotes, roll/expiry costs and stale/locked/crossed quote handling. Do not approximate that with midpoints or Black-Scholes for promotion decisions.

### Instrument hierarchy to test
Track: #142 / draft PR #143.

1. qualified long-duration R2 signal → shares as core trend vehicle;
2. exceptional liquid long-dated option structure → optional accelerator within the same trade-risk budget;
3. no qualifying stock but broad sector leadership → research selective 2x/3x sector ETF shares at risk-normalized size;
4. unallocated unborrowed investable cash → Treasury/SGOV reserve, excluding a small operational cash buffer;
5. stale/failed data → cash / no trade, never automatic leverage or silent substitution.

The research-only classifier hard-locks 3x sector expression behind an explicit experiment enable, defaults long-call eligibility to a 90–150 DTE research window, and includes a common-risk-budget splitter so shares plus options cannot silently double planned risk. No item in this hierarchy is promoted into paper/live execution by this document.

### Regime-dependent R2 exposure scaling
Track: #154.

New challenger motivated by recent trend-allocation research and the phase-1 downside result. It keeps every stock-level R2 rule frozen and tests whether a small point-in-time regime state can scale exposure 1.00x / 0.75x / 0.50x more efficiently than a hard portfolio drawdown throttle. Regime inputs are limited to observable market trend, realized volatility, breadth and correlation; no hindsight macro labels or special 2025 repair state is allowed.

Promotion hurdle: out-of-sample Sharpe or Calmar improvement >=10%, no worse max drawdown, >=90% of fixed-R2 CAGR, improved tail metric, <=25% extra turnover and no dependence on one sector/year. Kill if it merely duplicates the beta hedge or relies on fitting 2025.

### Valuation-extreme trend-reversal regime
Track: #146.

Tests whether public point-in-time valuation and yield-curve extremes identify reversal regimes that matter incrementally for the R2 Long-Runner. The experiment must hold stock-level R2 rules fixed, cannot increase risk in favorable regimes, must report 2025 separately without tuning it away, and must prove value beyond information already embedded in trend/volatility state.

## Workstream C — Quant Research Challenger queue

Master: #76.

Active research families include:
- #78 implied dispersion/correlation regime gate;
- #79 opportunistic insider-purchase overlay;
- #80 FINRA short-sale pressure/absorption;
- #83 attention-conditioned PEAD;
- #84 prospective earnings-language benchmark;
- #92 capacity/market-impact governor for institutional NAV;
- #93 predictable institutional rebalancing-flow pressure;
- #94 SEC 8-K tone + guidance revision drift;
- #98/#99 realized dispersion/correlation regime overlay;
- #105/#109 turnover-aware entry/hold hysteresis;
- #112 point-in-time option-surface divergence / skew shift;
- #114 volatility-managed risk budget;
- #115 shrinkage covariance + marginal-risk contribution;
- #133 layered downside / beta / tail / Treasury-reserve overlay;
- #138 state-dependent predictability / signal-confidence mosaic;
- #139 mega-cap concentration-constraint / stock-vs-sector relative-value overlay;
- #142/#143 shares/options/sector-proxy/SGOV instrument-expression hierarchy;
- #146 valuation-extreme trend-reversal regime gate;
- #151 pre-breakout liquidity-improvement challenger;
- #154 regime-dependent R2 exposure scaling.

Challenger governance:
- hypothesis and source before code;
- point-in-time data and no-lookahead controls;
- predeclared training/validation/holdout design;
- realistic costs and capacity assumptions;
- results excluding best trades / outliers;
- explicit null/kill path;
- no automatic promotion into paper/live rules.

## Workstream D — Institutional-scale portfolio readiness

Track: #92, #105/#109, #114, #115, #118, #133, #138, #139, #142, #146, #151, #154.

Before any claim that the strategy can scale toward $25M / $50M / $100M+ NAV, require:
- order-to-ADV and days-to-liquidate estimates;
- option capacity using bid/ask, volume, open interest and underlying liquidity together;
- implementation-shortfall and stress-exit scenarios;
- turnover-aware replacement/hysteresis;
- sector/theme/correlation-cluster concentration controls;
- marginal contribution to portfolio risk with shrinkage-stabilized covariance;
- stock-vs-sector expression choice when single-name concentration/capacity is unfavorable;
- signal reliability/predictability state so capital is not assumed equally productive everywhere;
- pre-breakout liquidity-path evidence versus one-day volume spikes;
- performance net of realistic capacity costs at each NAV tier.

## Workstream E — Commercial beta / marketable business

Master: #81. Long-term fund-readiness: #118.

The initial marketable product remains a research/subscription product, not autonomous customer execution or personalized portfolio management.

### Identity, subscriptions, tiers and billing
Track: #85 / draft PR #145, #88 / PR #101.

Current state:
- PR #145 refreshes the provider-neutral subscription projection on current `main`;
- duplicate/out-of-order billing events remain idempotent/fail-closed;
- entitlements remain server-side and deny-by-default outside ACTIVE/TRIAL states;
- privileged support/admin overrides are represented as auditable evidence and cannot grant access merely by existing;
- beta-readiness gate requires provenance/replay, performance methodology and claim controls, terms/privacy/support, retention, security/DR evidence and explicit live-execution disablement.

Still required:
- authentication/session/MFA provider adapter contract without selecting or purchasing a vendor;
- tenant-isolation fixtures/tests for any persistence layer;
- provider-neutral billing-webhook signature verification and reconciliation job contract;
- account deletion/retention workflow and immutable audit-event schema;
- no card/payment secrets stored unless explicitly required and reviewed.

### Automated candidate / alert management
Track: #89 / draft PR #144.

Current state:
- current-main dry-run desired-state planner exists;
- deterministic CREATE / UPDATE / DISABLE / MIGRATE_STRATEGY / NO_CHANGE / DATA_ERROR diff;
- stale/incomplete ranked-candidate sources fail closed;
- strategy-version changes require explicit migration;
- every plan is hard-locked to `dry_run=True` and `mutation_allowed=False`.

Still required before any real alert mutation:
- observed-state adapter contract;
- immutable desired/observed diff audit artifact;
- reconciliation/drift and future adapter rate-limit/retry policy;
- proof the planner cannot mutate the paper ledger;
- explicit user approval for the first real TradingView mutation.

### Customer-facing research outputs and delivery
Track: #87 / PR #100 / PR #111, #116 / draft PR #150.

Current safe implementation:
- draft PR #150 adds an immutable report-provenance manifest contract;
- deterministic evidence hashing and report identity;
- explicit ACTUAL / PAPER / BACKTEST / HYPOTHETICAL / NONE basis separation;
- source freshness/error states cannot silently disappear;
- customer-safe provenance footer excludes internal archive/delivery infrastructure identifiers.

Still required:
- readable morning/evening research outputs and archive;
- source/data cutoff timestamps surfaced consistently;
- monitored scheduled delivery with correlation IDs;
- idempotent replay without duplicate delivery or ledger mutation;
- explicit stale/data-error labeling rather than apparently healthy output;
- tested backup/restore and incident-disable path.

### Performance and audit history
Track: #86 / #113 / #116 / PR #96 / draft PR #140 / draft PR #150.

Current safe implementation:
- draft PR #140 adds a machine-readable performance-methodology contract;
- strict ACTUAL / PAPER / BACKTEST / HYPOTHETICAL separation;
- predeclared benchmark/version checks;
- deterministic methodology hash;
- executable-side long-option mark requirement;
- fail-closed stale/locked/crossed/missing option performance evidence;
- gross/net separation when costs are estimated;
- draft PR #150 links report identity to immutable source/model/methodology evidence.

Still required:
- canonical NAV calculator and fixtures for stock/ETF/options/add/partial/roll/assignment cases;
- benchmark and cost-model registries;
- minimum sample/period rules for annualized/performance claims;
- methodology-change invalidation into the claim registry;
- full provenance/replay evidence across generated and delivered reports.

### Security, privacy, secrets and environment separation
Track: #103 / PR #104, #87 / PR #111.

Required:
- research/staging/production separation;
- least-privilege roles and secret lifecycle;
- no repository/customer-output secrets;
- tenant isolation and privileged-action audit;
- MFA/strong authentication for privileged/admin access;
- privacy-minimized analytics and retention/deletion hooks;
- monitored auth/authorization/secret-access anomalies;
- recovery and credential-rotation runbooks.

### Legal/compliance-readiness and claims
Track: #86 / #97 / PR #96.

Repository controls must remain questions/gates, not legal conclusions. Before any public launch or performance marketing require:
- disclosure inventory by channel;
- terms/privacy/support requirements;
- marketing-claim evidence registry;
- hypothetical/backtest/paper labeling rules;
- feature-change triggers that reopen external review;
- external legal/compliance review reference for the actual product scope.

No repository document may represent the service as approved, registered, exempt, certified or compliant without independent evidence and applicable external review.

### Website, positioning, pricing and analytics
Track: #107 / PR #108, #88 / PR #101, PR #117.

Plan but do not publish:
- brand hierarchy and consistent visual/readability standards;
- ideal customer / non-target user / product promise;
- home / how-it-works / sample report / methodology / evidence / pricing / disclosures / privacy-security / FAQ-support / sign-in-account surfaces;
- provider-neutral pricing hypotheses and conservative unit economics;
- acquisition → account → acknowledgement → subscription → first report → first-week activation → retained subscriber → cancellation funnel;
- privacy-minimized activation/engagement/retention/churn/feedback events;
- commercial beta launch and rollback/no-launch checklist.

## Commercial beta launch gate

Commercial beta is NO-GO until all are evidenced:
1. reproducible research outputs from immutable/versioned inputs;
2. performance bases cannot mix;
3. benchmark/cost/option-mark methodology is versioned and tested;
4. report delivery is monitored and replay-safe;
5. authentication/entitlement/tenant isolation tests pass;
6. billing events are idempotent and reconciled with entitlements;
7. customer-facing provenance/replay evidence exists;
8. security/privacy launch evidence passes;
9. backup/restore and incident-disable drills pass;
10. disclosures/terms/privacy/support requirements are complete for external review;
11. applicable external legal/compliance review is documented for the exact launch scope;
12. support owner, customer feedback loop and rollback path exist;
13. no public claim exceeds its evidence/review status;
14. no live trading, brokerage execution or personalized managed-account functionality is implied or enabled.

## Long-term Convex Ridge path

Track: #118.

Progression remains deliberately staged:
research system → forward paper fund → proprietary-capital readiness → separately approved proprietary live track record → institutional manager/fund readiness → only then any outside-capital consideration.

Daily Alpha Research can become a commercial research/distribution product without forcing changes that weaken the investment process or collapsing the separation between research, paper, actual and hypothetical evidence.

## Non-negotiable safety boundaries

- No live trading is authorized.
- No disconnected research rule self-promotes into paper/live execution.
- No stale ORATS/data failure silently becomes stock, option, leveraged ETF or other exposure.
- No leverage increase occurs merely because volatility is low or idle capital exists.
- No paid service, public website, customer outreach, public performance claim, production AWS deployment, real TradingView alert mutation, capital deployment, fundraising or legal/compliance conclusion occurs without the required explicit approval and review gates.
