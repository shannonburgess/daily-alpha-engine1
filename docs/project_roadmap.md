# Daily Alpha Project Roadmap

Updated: 2026-08-17 evening, Pacific Time

## Current operating boundary

Daily Alpha remains a research and paper-trading platform. Canonical v2.4 now uses the corrected 70% full Earnings Gap & Go threshold and a 60%-<70% `EARNINGS_GAP_GO_EARLY` research/watch band. The canonical ADX entry floor is 17. Paper ENTRY and ADD actions require explicit human approval and remain capped by the existing 0.50% NAV hard-risk ceiling. Live brokerage execution remains disabled.

The current production-research split is intentional: stable v2.4 paper behavior stays frozen while new R2 Long-Runner, portfolio-overlay, options, sector-ETF, SGOV, downside-risk and commercialization ideas are tested in disconnected research/draft branches.

## Workstream A — Paper-trading and staging readiness

### Completed / landed
- v2.4 historical baseline aligned to 70% Gap & Go; PR #77 merged.
- server-side Top-20 + open-position execution-universe scanner; PR #124 merged.
- next-regular-session staging/execution lifecycle; PR #126 merged.
- ADX17 + explicit human approval for ENTRY/ADD; PR #130 merged.
- gated automatic deployment of paper-runtime changes to staging; PR #131 merged.
- main deployment gate includes a paper-approval rehearsal before staging mutation.

### Remaining evidence gates
1. Confirm scheduled close scan produces staged actions only, with zero after-hours paper fills.
2. Confirm 9:45 AM ET revalidation uses fresh market/ORATS data and either executes an approved paper action or records CANCEL / DATA_ERROR.
3. Confirm 10:05 AM ET retry path remains fail-closed for persistent data errors.
4. Reconcile paper ledger, runner state, intended versus executed instrument, fees/slippage and duplicate/idempotency behavior.
5. Preserve live-trading lockout and separate any future production/live authorization from this roadmap.

## Workstream B — Active research backlog

### Earnings EARLY
Track: #71 / draft PR #134.

Current state:
- refreshed on current `main` after the canonical baseline correction;
- `NO_ENTRY`, 25% starter-only and 25%→50% T+1/T+2 confirmation scenarios remain research-only;
- event-high and event-close confirmations stay separate;
- point-in-time event/option data, MRVL isolation, best-trade exclusion and an explicit null-result path are required;
- current test workflow is green.

Promotion gate: no EARLY starter enters paper/live until an out-of-sample cohort proves incremental value without depending on MRVL or another single outlier.

### Pre-Catalyst Drift
Track: #72 / draft PR #135.

Current state:
- refreshed on current `main`;
- hard `event_known_date` boundary prevents lookahead;
- `PRE_CATALYST_WATCH` / `PRE_CATALYST_RUN` remain descriptive research states only;
- matched-control and incremental-value tests are required to prove benefit beyond ordinary momentum/R2 trend;
- current test workflow is green.

Promotion gate: no scheduled non-earnings catalyst becomes a trade authorization without point-in-time source provenance, sufficient N, matched-control evidence and walk-forward stability.

### ORATS reliability
Track: #75 / #106 / PR #82 / PR #95 / draft PR #137.

Current state:
- heavy research workflows are serialized;
- standard ORATS client has bounded 429/transient retry and distinct rate-limit classification;
- refreshed historical transport on current `main` distinguishes RATE_LIMITED / AUTH / REQUEST / HTTP / malformed-data failures and is green;
- strict compatibility-route helper now allows a legacy-route fallback only on explicit endpoint incompatibility, never on 429, 401/403, network exhaustion, malformed data or ordinary bad requests.

Remaining:
- wire `fetch_orats_history()` itself to the strict transport/route helper;
- update historical option callers after reconciling older stacked PR #110;
- add safe per-run caching/batching where it materially reduces duplicate historical requests;
- preserve `DATA_ERROR` / `RATE_LIMITED` / `NO_QUALIFIED_OPTION` as distinct states end-to-end.

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
Track: PR #127, #114, #115, #133.

Required independent attribution tests:
- R2 shares-only baseline;
- SGOV treasury-reserve sleeve for unused investable capital, retaining an operational cash buffer;
- stock + long-dated option accelerator under one combined risk budget;
- selective 2x / 3x sector proxy when sector leadership is strong but no individual stock qualifies;
- volatility/drawdown risk-budget reduction;
- dynamic SPY/QQQ beta hedge;
- small index-put tail hedge / put-spread / collar cost challenger;
- shrinkage-covariance marginal-risk-contribution governor.

Important early result from PR #127: the prototype SGOV reserve improved the tested R2 portfolio, while the first drawdown-throttle schedule did not. Those results are not promotion-grade because the prototype still needs the corrected ADX17 and 55-day Long-Runner signal lifecycle plus point-in-time universe cleanup.

### Instrument hierarchy to test
1. qualified long-duration R2 signal → shares as core trend vehicle;
2. exceptional liquid long-dated option structure → optional accelerator within the same trade-risk budget;
3. no qualifying stock but broad sector leadership → research selective 2x/3x sector ETF shares at risk-normalized size;
4. unallocated investable cash → SGOV treasury reserve, excluding a small operational cash buffer;
5. stale/failed data → cash / no trade, never automatic leverage or silent substitution.

No item in this hierarchy is promoted into paper/live execution by this document.

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
- #133 layered downside / beta / tail / SGOV overlay;
- #138 state-dependent predictability / signal-confidence mosaic;
- #139 mega-cap concentration-constraint / stock-vs-sector relative-value overlay.

Challenger governance:
- hypothesis and source before code;
- point-in-time data and no-lookahead controls;
- predeclared training/validation/holdout design;
- realistic costs and capacity assumptions;
- results excluding best trades / outliers;
- explicit null/kill path;
- no automatic promotion into paper/live rules.

## Workstream D — Institutional-scale portfolio readiness

Track: #92, #105/#109, #114, #115, #118, #133, #138, #139.

Before any claim that the strategy can scale toward $25M / $50M / $100M+ NAV, require:
- order-to-ADV and days-to-liquidate estimates;
- option capacity using bid/ask, volume, open interest and underlying liquidity together;
- implementation-shortfall and stress-exit scenarios;
- turnover-aware replacement/hysteresis;
- sector/theme/correlation-cluster concentration controls;
- marginal contribution to portfolio risk with shrinkage-stabilized covariance;
- stock-vs-sector expression choice when single-name concentration/capacity is unfavorable;
- signal reliability/predictability state so capital is not assumed equally productive everywhere;
- performance net of realistic capacity costs at each NAV tier.

## Workstream E — Commercial beta / marketable business

Master: #81. Long-term fund-readiness: #118.

The initial marketable product remains a research/subscription product, not autonomous execution or personalized portfolio management.

### Identity, subscriptions, tiers and billing
Track: #85 / PR #91, #88 / PR #101.

Required:
- immutable customer/account ID;
- server-side authentication and fail-closed entitlements;
- tier boundaries and explicit exclusions;
- subscription lifecycle: TRIAL / ACTIVE / PAST_DUE / CANCELED / EXPIRED / SUSPENDED;
- provider-neutral billing adapter and webhook contract;
- idempotency / replay protection / billing-entitlement reconciliation;
- cancellation, reactivation, support and account-change paths;
- no card/payment secrets stored unless explicitly required and reviewed.

### Customer-facing research outputs and delivery
Track: #87 / PR #100 / PR #111, #116.

Required:
- readable morning/evening research outputs and archive;
- immutable report IDs and source/data cutoff timestamps;
- deterministic provenance manifest linking inputs, strategy/model/methodology version and git/build hash;
- monitored scheduled delivery with correlation IDs;
- idempotent replay without duplicate delivery or ledger mutation;
- explicit stale/data-error labeling rather than apparently healthy output;
- tested backup/restore and incident-disable path.

### Performance and audit history
Track: #86 / #113 / #116 / PR #96 / draft PR #140.

Current safe implementation:
- draft PR #140 adds a machine-readable performance-methodology contract;
- strict ACTUAL / PAPER / BACKTEST / HYPOTHETICAL separation;
- predeclared benchmark/version checks;
- deterministic methodology hash;
- executable-side long-option mark requirement;
- fail-closed stale/locked/crossed/missing option performance evidence;
- gross/net separation when costs are estimated.

Still required:
- canonical NAV calculator and fixtures for stock/ETF/options/add/partial/roll/assignment cases;
- benchmark and cost-model registries;
- minimum sample/period rules for annualized/performance claims;
- methodology-change invalidation into the claim registry;
- provenance/replay evidence.

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
- No research rule self-promotes into paper/live execution.
- No stale ORATS/data failure silently becomes stock, option, leveraged ETF or other exposure.
- No leverage increase occurs merely because volatility is low or idle capital exists.
- No paid service, public website, customer outreach, public performance claim, production AWS deployment, real TradingView alert mutation, capital deployment, fundraising or legal/compliance conclusion occurs without the required explicit approval and review gates.
