# Daily Alpha Project Roadmap

Updated: 2026-08-17 Pacific Time

## Current operating boundary

Daily Alpha remains a research and paper-trading platform. Pine v2.4 is the current strategy family in repository `main`, with the earnings Gap & Go sleeve merged and the 60%-<70% `EARNINGS_GAP_GO_EARLY` band research/watch-only. Live brokerage execution is not authorized.

## Phase 1 — Finish staging

Target: operationally complete staging by **2026-08-28**.

1. **v2.4 research-baseline alignment** — correct the historical Gap & Go baseline to the canonical 70% full-entry threshold and retain 60%-<70% as non-executable EARLY research. Track: #70 / PR #77. Current draft CI is green; merge remains approval-gated.
2. **Real TradingView → AWS validation** — prove a real v2.4 TradingView-origin event reaches API Gateway → Pine ingress → SQS → Pine processor, passes fresh ORATS and portfolio-risk gates, and produces the correct paper result. Requires explicit user approval before changing the live TradingView alert or redeploying staging.
3. **Runner lifecycle validation** — prove starter → ADD #1 → ADD #2 → 25% harvest → final EXIT end-to-end against the durable paper ledger with correct instrument fills and idempotency.
4. **Newsletter delivery** — automatically deliver the finished report after scheduled staging publication while preserving readable output QC, immutable history, and delivery audit events.
5. **Operations hardening** — monitoring/alarms, failure notifications, ledger reconciliation, queue/DLQ checks, source/data freshness, reproducible runtime configuration, and runbook coverage.
6. **ORATS reliability** — shared workflow serialization, bounded retry/backoff for 429/transient failures, explicit `RATE_LIMITED` classification, fail-closed auth/malformed/stale handling, and caching/batching where useful. Track: #75 / PR #82 / PR #95. Both active reliability drafts are CI-green; caching/batching and historical-fetcher coverage remain.

## Phase 2 — Research expansion and candidate automation

Target: **2026-09-11**.

1. Controlled candidate → TradingView alert-management workflow; no manual alert sprawl. Track: #89.
2. Earnings EARLY research (#71 / PR #73), keeping hypothetical starter/confirmation policies out of paper execution until separately approved.
3. Point-in-time Pre-Catalyst Drift research (#72 / PR #74).
4. Quant Research Challenger queue (#76) for missed winners, accepted losers, threshold-near misses, regime dependence, tail dependence, and new falsifiable hypotheses.
5. Active challengers include point-in-time SEC 8-K earnings tone/guidance revision drift (#94) and a cross-sectional dispersion/correlation regime overlay for momentum risk (#98).
6. Promote no challenger signal automatically; every strategy/risk rule requires evidence, documented sample size, walk-forward or prospective validation where appropriate, and explicit approval.

## Phase 3 — Production architecture readiness

Target: **2026-10-16** for controlled testing readiness; live authorization is a separate decision.

- hard environment separation: research/staging/production;
- least-privilege IAM and secrets management;
- release approvals and immutable deployment audit trail;
- reconciliation and kill switches;
- broker adapter contract and sandbox/integration testing;
- incident response, backups, recovery objectives, and change rollback;
- capacity/liquidity controls so portfolio growth cannot silently exceed strategy assumptions.

## Phase 4 — Customer/subscription commercial beta

Target: **2026-11-20**, subject to readiness gates rather than date alone.

The first commercial product should be a research/subscription product, not autonomous live execution.

Required workstreams:

- **Product** — define target customer, product promise, edition/tier boundaries, feature entitlements, cadence, onboarding, cancellation, support and feedback loop. Track: #88.
- **Identity / entitlement** — secure customer authentication, account state, subscription entitlements, admin access and audit logging. Track: #85 / PR #91.
- **Billing design** — provider-neutral subscription/payment architecture, webhooks/idempotency, failed-payment states and refund/cancellation policy; no service purchase or activation without approval. Track: #85 / PR #91.
- **Customer outputs** — morning/evening research, dashboard, watchlists and educational/explainability layers with clear timestamps and data-quality labels.
- **Performance evidence** — immutable signal history and strict separation of actual, paper, backtest and hypothetical results; methodology/version history; benchmark and drawdown reporting; no cherry-picked marketing claims. Track: #86 / PR #96.
- **Disclosures / legal readiness** — disclosure inventory, marketing-claim review gate, terms/privacy/support requirements and external legal/compliance review before public launch. Track: #86 / #97 / PR #96.
- **Reliability** — monitored delivery, backups/DR, incident process, source-freshness/dependency status, customer-facing status expectations and support escalation. Track: #87.
- **Analytics** — activation, engagement, retention/churn, delivery success, feature use and feedback without compromising customer privacy. Track: #88.
- **Website / positioning** — value proposition, methodology explanation, sample product, pricing architecture, FAQ, disclosure surfaces and launch checklist; do not publish before approval.

## Commercial beta launch gates

Commercial beta is **NO-GO** unless all of the following are true:

1. research and paper execution outputs are reproducible from immutable inputs and versioned rules;
2. customer-facing performance labels cannot mix actual, paper, backtest or hypothetical results;
3. critical scheduled report delivery is monitored and has a tested retry/escalation path;
4. authentication/entitlement tests prove customers cannot access the wrong tier or another customer's data;
5. billing events are idempotent and entitlement state is reconciled;
6. disclosures, terms/privacy and marketing claims have completed the required external review;
7. the regulatory perimeter and launch scope have an auditable external-counsel/compliance review reference, and material feature changes reopen that review (#97);
8. secrets are not stored in source or customer-visible outputs;
9. backups/recovery and incident-response procedures are tested;
10. the beta has a defined support owner, feedback loop and rollback/disable path;
11. no live trading or brokerage execution is implied or enabled without a separately approved program.

## Safety boundaries

- No live brokerage execution is authorized.
- Stale/unavailable execution-critical ORATS data must fail closed and must not silently trigger stock fallback.
- Research challengers cannot promote themselves into paper/live execution.
- Paid services, public publishing, customer outreach, legal/compliance claims and production deployment require explicit approval.
- Repository evidence/claim gates are operational controls only and must never be represented as regulator or legal approval.
