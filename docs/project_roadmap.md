# Daily Alpha Project Roadmap

Updated: 2026-08-17 Pacific Time

## Current operating boundary

Daily Alpha remains a research and paper-trading platform. Pine v2.4 is the current strategy family in repository `main`, with the earnings Gap & Go sleeve merged and the 60%-<70% `EARNINGS_GAP_GO_EARLY` band research/watch-only. Live brokerage execution is not authorized.

## Phase 1 — Finish staging

Target: operationally complete staging by **2026-08-28**.

1. **v2.4 research-baseline alignment** — correct the historical Gap & Go baseline to the canonical 70% full-entry threshold and retain 60%-<70% as non-executable EARLY research. Track: #70 / PR #77. Current test, sensitivity and earnings-gap workflows are green; merge remains approval-gated.
2. **Real TradingView → AWS validation** — prove a real v2.4 TradingView-origin event reaches API Gateway → Pine ingress → SQS → Pine processor, passes fresh ORATS and portfolio-risk gates, and produces the correct paper result. Requires explicit user approval before changing the live TradingView alert or redeploying staging.
3. **Runner lifecycle validation** — prove starter → ADD #1 → ADD #2 → 25% harvest → final EXIT end-to-end against the durable paper ledger with correct instrument fills and idempotency.
4. **Newsletter delivery** — automatically deliver the finished report after scheduled staging publication while preserving readable output QC, immutable history, and delivery audit events.
5. **Operations hardening** — monitoring/alarms, failure notifications, ledger reconciliation, queue/DLQ checks, source/data freshness, reproducible runtime configuration, and runbook coverage.
6. **ORATS reliability** — shared workflow serialization, bounded retry/backoff for 429/transient failures, explicit `RATE_LIMITED` classification, fail-closed auth/malformed/stale handling, and caching/batching where useful. Track: #75 / PR #82 / PR #95 / #106 / PR #110. PR #110 test and historical-options workflows are green. The remaining daily-history compatibility fallback should be narrowed only after PR #77 lands so reliability work cannot accidentally reintroduce the stale v2.4 baseline.

## Phase 2 — Research expansion and candidate automation

Target: **2026-09-11**.

1. **Controlled candidate → TradingView alert lifecycle** — deterministic desired-state planning with explicit CREATE / UPDATE / DISABLE / strategy-migration / NO_CHANGE / DATA_ERROR actions. Track: #89 / PR #102. Current planner is dry-run-only and hard-locked against mutation.
2. **Earnings EARLY research** — compare no-entry versus hypothetical starter/confirmation policies while keeping 60%-<70% events outside paper execution. Track: #71 / PR #73.
3. **Point-in-time Pre-Catalyst Drift research** — scheduled non-earnings event study with event-known timestamps and no-lookahead controls. Track: #72 / PR #74.
4. **Quant Research Challenger queue** — missed winners, accepted losers, threshold-near misses, regime dependence, tail dependence, transaction-cost sensitivity and new falsifiable hypotheses. Track: #76.
5. **Active challenger families**:
   - #94 — point-in-time SEC 8-K earnings tone + guidance revision drift;
   - #98 / PR #99 — cross-sectional dispersion/correlation regime overlay for momentum risk and portfolio sizing;
   - #105 / PR #109 — turnover-aware entry/hold hysteresis for lower implementation churn and stronger institutional-scale net capacity;
   - #112 — timestamp-aligned option-surface divergence / skew-shift overlay using ORATS;
   - #114 — volatility-managed portfolio risk-budget overlay testing whether realized-volatility state can improve drawdown/tail behavior without changing signal selection or increasing leverage in calm regimes.
6. Promote no challenger signal automatically; every strategy/risk rule requires point-in-time evidence, documented sample size, best-trade/outlier exclusion, realistic costs, walk-forward or prospective validation where appropriate, explicit null/kill criteria, and explicit approval.

## Phase 3 — Production architecture readiness

Target: **2026-10-16** for controlled testing readiness; live authorization is a separate decision.

- hard environment separation: research/staging/production;
- least-privilege IAM and secrets management;
- release approvals and immutable deployment audit trail;
- reconciliation and kill switches;
- broker adapter contract and sandbox/integration testing;
- incident response, backups, recovery objectives, and change rollback;
- capacity/liquidity controls so portfolio growth cannot silently exceed strategy assumptions (#92);
- performance/benchmark/transaction-cost methodology that remains reproducible across research, paper and any future production environment (#113).

## Phase 4 — Customer/subscription commercial beta

Target: **2026-11-20**, subject to readiness gates rather than date alone.

The first commercial product should be a research/subscription product, not autonomous live execution.

Required workstreams:

- **Product** — define target customer, product promise, edition/tier boundaries, feature entitlements, cadence, onboarding, cancellation, support and feedback loop. Track: #88 / PR #101.
- **Identity / entitlement** — secure customer authentication, account state, subscription entitlements, admin access and audit logging. Track: #85 / PR #91.
- **Billing design** — provider-neutral subscription/payment architecture, webhooks/idempotency, failed-payment states and refund/cancellation policy; no service purchase or activation without approval. Track: #85 / PR #91.
- **Customer outputs** — morning/evening research, dashboard, watchlists and educational/explainability layers with clear timestamps and data-quality labels.
- **Performance evidence** — immutable signal history and strict separation of ACTUAL, PAPER, BACKTEST and HYPOTHETICAL results; methodology/version history; benchmark, transaction-cost and drawdown reporting; no cherry-picked marketing claims. Track: #86 / PR #96 / #113.
- **Disclosures / legal readiness** — disclosure inventory, marketing-claim review gate, terms/privacy/support requirements and external legal/compliance review before public launch. Track: #86 / #97 / PR #96.
- **Security / privacy** — customer/data classification, authentication and authorization assurance, tenant isolation, secrets, logging, retention, privacy-minimized analytics, incident evidence and fail-closed beta security gate. Track: #103 / PR #104.
- **Reliability / disaster recovery** — monitored delivery, immutable delivery observations, retry/idempotency evidence, backups/restore tests, internal RPO/RTO hypotheses, incident severity/runbooks, publication-disable controls and dependency-outage behavior. Track: #87 / PR #100 / PR #111. PR #111 test workflow is green.
- **Analytics** — activation, engagement, retention/churn, delivery success, feature use and structured feedback without compromising customer privacy. Track: #88 / PR #101 / #107 / PR #108.
- **Website / positioning / go-to-market** — category, ideal customer, value proposition, methodology explanation, sample product, pricing/unit-economics hypotheses, FAQ, disclosure surfaces, acquisition→activation→retention funnel and launch scorecard. Track: #107 / PR #108. Do not publish before approval.

## Commercial beta launch gates

Commercial beta is **NO-GO** unless all of the following are true:

1. research and paper execution outputs are reproducible from immutable inputs and versioned rules;
2. customer-facing performance labels cannot mix ACTUAL, PAPER, BACKTEST or HYPOTHETICAL results;
3. benchmark, return, option-fill and transaction-cost methodology is versioned and reproducible (#113);
4. critical scheduled report delivery is monitored and has a tested retry/escalation path (#100);
5. authentication/entitlement tests prove customers cannot access the wrong tier or another customer's data;
6. billing events are idempotent and entitlement state is reconciled;
7. disclosures, terms/privacy and marketing claims have completed the required external review;
8. the regulatory perimeter and launch scope have an auditable external-counsel/compliance review reference, and material feature changes reopen that review (#97);
9. secrets are not stored in source or customer-visible outputs;
10. security/privacy beta evidence is complete and passing (#103 / PR #104);
11. backups/recovery and incident-response procedures are tested with restore-integrity evidence (#87 / PR #111);
12. the beta has a defined support owner, feedback loop and rollback/disable path;
13. no live trading or brokerage execution is implied or enabled without a separately approved program.

## Current approval gates / dependencies

- **PR #77**: v2.4 70% historical baseline correction is green but requires explicit merge approval.
- **TradingView + staging redeploy**: after baseline approval, changing the user-facing v2.4 TradingView alert and redeploying staging require explicit approval.
- **PR #95 → PR #110 stack**: ORATS transport reliability drafts are safe/research-only; PR #110 is stacked on #95 and should be retargeted after #95 is approved/merged.
- **PR #73 Earnings EARLY**: remains research-only and should not be interpreted as an executable starter rule.
- **Customer beta**: external legal/compliance review, security evidence, DR evidence and commercial launch approval remain mandatory gates.

## Safety boundaries

- No live brokerage execution is authorized.
- Stale/unavailable execution-critical ORATS data must fail closed and must not silently trigger stock fallback.
- Research challengers cannot promote themselves into paper/live execution.
- Paid services, public publishing, customer outreach, legal/compliance claims and production deployment require explicit approval.
- Repository evidence/claim gates are operational controls only and must never be represented as regulator or legal approval.
