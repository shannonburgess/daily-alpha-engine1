# Daily Alpha Commercial Go-To-Market Readiness

Status: **internal planning only**  
Tracks: #81, #88, #107  
Safety boundary: this document does not publish a website, set public pricing, contact prospects, process payments, make legal/compliance claims, deploy production, or enable live trading.

## 1. Initial product category and customer

### Working category

**Daily systematic market research and risk intelligence for self-directed investors.**

This is intentionally narrower than “asset manager,” “robo-adviser,” “broker,” or “autonomous trading system.” Any eventual legal/regulatory characterization remains subject to #97 and external review.

### Initial ideal customer profile

The first beta should target a self-directed investor who:

- actively allocates capital in U.S. stocks, ETFs and/or listed options;
- wants a disciplined daily process rather than an unstructured stream of trade ideas;
- can understand probabilistic setups, risk, invalidation, market regime and position sizing;
- values research transparency, historical evidence and explicit data-quality flags;
- does not expect Daily Alpha to custody assets or automatically trade a brokerage account.

### Explicit non-target users for first beta

- users seeking guaranteed returns;
- users seeking individualized fiduciary portfolio management;
- users who cannot evaluate investment risk;
- users seeking autonomous brokerage execution;
- users who require institutional APIs, bespoke mandates or enterprise support before those products exist.

## 2. Positioning architecture

### One-sentence working promise

> Daily Alpha turns market regime, sector rotation, price/volume behavior, options context, catalysts and portfolio risk into a disciplined daily research process with explicit entries, invalidations, evidence and decision quality tracking.

This is an internal working statement, not approved public marketing copy.

### Differentiation pillars

1. **Process over predictions** — regime → rotation → setup → instrument → portfolio fit → execution plan → management → measurement.
2. **Evidence over anecdotes** — immutable dated inputs, versioned model rules and reproducible research/paper performance.
3. **Risk before reward** — position risk, portfolio concentration, earnings/event risk, liquidity and data freshness are explicit gates.
4. **Explainable daily output** — the reader can see why an opportunity ranked, what would invalidate it and what data is unavailable.
5. **Research discipline** — new ideas enter a Challenger queue and must survive point-in-time/out-of-sample testing before promotion.
6. **Institutional-scale design** — capacity, implementation cost, correlation and operational reliability are considered before the system reaches institutional NAV.

### Proof hierarchy

Public trust should eventually rely on evidence in this order:

1. methodology and decision process;
2. versioned signal/recommendation history;
3. clearly separated ACTUAL / PAPER / BACKTEST / HYPOTHETICAL evidence under #86;
4. delivery/reliability evidence under #87;
5. security/privacy controls under #103;
6. transparent limitations and data-unavailable states;
7. external legal/compliance review where required under #97.

Testimonials, social proof and promotional language must never substitute for evidence.

## 3. Product packaging

PR #101 / issue #88 defines the initial `RESEARCH` and `RESEARCH_PLUS` direction. Go-to-market packaging should stay deliberately simple.

### Packaging rule

Each tier must answer:

- Who is this for?
- What daily/weekly outputs are included?
- Which methodology/explainability surfaces are included?
- Which archives/history are included?
- Which alerts/notifications are included?
- What support level is included?
- What is explicitly **not** included?

### Exclusions for the initial research beta

Unless separately approved after technical and external review, no tier includes:

- personalized portfolio management;
- discretionary/advisory relationship claims;
- autonomous brokerage execution;
- custody;
- guaranteed returns;
- live-trading authorization;
- customer-specific risk optimization based on a linked brokerage account.

## 4. Website information architecture

Plan the following surfaces before design/build. Every page must have a single job and a launch dependency.

| Page | Primary job | Required dependencies |
|---|---|---|
| Home | explain category, audience and value in under one minute | approved positioning + claims registry |
| How It Works | explain regime → rotation → setup → risk → execution → measurement | methodology/versioning docs |
| Sample Daily Brief | let a prospect evaluate the actual product | delivery/readability QC + dated sample rules |
| Methodology | explain Alpha Score, event states, data freshness and limitations | research/version governance |
| Performance & Evidence | present only approved, reproducible evidence | #86 + external review where applicable |
| Plans | compare research tiers and exclusions | #88/#85 + approved pricing |
| Security & Privacy | describe actual controls and data practices | #103 + privacy/legal review |
| Risk / Disclosures | communicate product scope and investment/data risks | #97 external review |
| FAQ | remove purchase/onboarding friction | product/support decisions |
| Support | explain help, response paths and escalation | #88 support model |
| Sign In / Account | authenticate and manage account | #85 identity/entitlements |
| Billing | subscription changes/cancellation | #85 billing reconciliation |

### Page-level content rule

Every customer-facing page should identify which of these it is doing:

- educate;
- demonstrate;
- provide evidence;
- disclose risk/limits;
- convert;
- onboard;
- support.

Do not mix unsupported performance claims into educational or product-description copy.

## 5. Sample report as the primary product proof

Before spending on acquisition, the sample Daily Alpha brief should be the strongest demonstration of the product.

Requirements:

- date stamped and model/version stamped;
- real historical or current research context clearly labeled;
- no fabricated option quote, indicator or wall data;
- DATA UNAVAILABLE / DATA ERROR states shown honestly;
- readable PDF/web output with no clipped/tiny/blurry content;
- short “how to read this” guide for a first-time reader;
- explicit separation between research setup and executed trade;
- explicit risk/invalidation and “cash/no trade” capability;
- evidence lineage available internally for each quantitative claim.

## 6. Pricing research framework

No public price is selected in this document.

### Pricing hypotheses to test

- monthly only vs monthly + discounted annual;
- single research tier vs two-tier `RESEARCH` / `RESEARCH_PLUS`;
- free sample brief vs limited free archive vs no free tier;
- trial vs money-back/cancel-anytime messaging, subject to external review and operational ability;
- beta founder pricing vs standard pricing later;
- individual research subscription first; institutional/enterprise packaging deferred.

### Unit-economics model required before public price

For each price hypothesis estimate:

- gross subscription revenue;
- payment-processing cost assumption;
- market/options/data-vendor cost allocation;
- email/storage/compute/monitoring allocation;
- customer-support cost;
- expected refunds/chargebacks where relevant;
- customer acquisition cost assumption;
- gross margin;
- contribution margin;
- break-even customers;
- churn sensitivity;
- annual-plan cash-flow benefit and refund risk.

Use conservative ranges rather than one-point forecasts.

### Pricing decision gate

A price hypothesis is not launch-ready unless:

- entitlements map cleanly to the tier;
- billing/account-state reconciliation is tested;
- cancellation/reactivation is tested;
- support burden is understood;
- claims/disclosures are reviewed;
- unit economics remain acceptable under a downside case.

## 7. Acquisition and activation funnel

The beta funnel should be measurable without invasive tracking.

### Funnel states

1. `QUALIFIED_VISITOR`
2. `SAMPLE_ENGAGED`
3. `ACCOUNT_CREATED`
4. `ACKNOWLEDGEMENTS_COMPLETE`
5. `SUBSCRIPTION_ACTIVE`
6. `FIRST_REPORT_OPENED`
7. `FIRST_WEEK_ACTIVATED`
8. `RETAINED`
9. `CANCELED`
10. `RETURNED`

### First-week activation definition

A customer should not be counted as activated merely because payment succeeded. A candidate initial definition is:

- opened multiple scheduled outputs;
- viewed methodology/how-to-read content;
- used at least one core research surface such as Top 3, rotation, portfolio-risk view or archive;
- did not encounter unresolved delivery/access failure.

The exact threshold is an experiment and must not be tuned retroactively to make retention look better.

### Privacy-minimized analytics

Prefer:

- pseudonymous customer/account ID;
- event name;
- timestamp;
- product tier;
- app/report surface;
- success/failure reason;
- coarse device/channel metadata only when operationally useful.

Avoid collecting brokerage credentials, account holdings, payment-card data, unnecessary location history or sensitive free-form content for marketing analytics.

## 8. Initial acquisition experiments

Do not buy ads or contact prospects until approved. The internal experiment queue can prepare:

- sample Daily Alpha brief landing page;
- methodology explainer;
- founder/story page only if claims are documented and appropriate;
- newsletter sample/archive preview;
- waitlist/interest expression only after privacy/terms handling is ready;
- educational market-regime/rotation content that demonstrates process without turning into unsupported performance advertising;
- referral/testimonial concepts only after external review determines requirements and controls.

Each experiment should define hypothesis, audience, success metric, minimum sample, cost cap and stop condition before launch.

## 9. Customer trust controls

### Prohibited unsupported marketing patterns

Do not publish claims such as:

- “guaranteed returns”;
- “beats the market” without approved reproducible evidence and required review;
- “institutional hedge fund returns”;
- “AI predicts the market”;
- “X% win rate” without basis, sample size, time period, methodology and evidence-class disclosure;
- cherry-picked winner screenshots as performance proof;
- annualized backtest/paper results presented as actual customer returns;
- “secure,” “certified” or “compliant” claims that exceed the actual reviewed controls.

### Claim registry dependency

Every quantitative or trust claim should map to:

- claim ID;
- exact text/meaning;
- evidence basis;
- ACTUAL/PAPER/BACKTEST/HYPOTHETICAL classification if performance-related;
- limitations;
- owner;
- review status;
- review/expiration date;
- channel(s) where approved.

This is governed by #86 / PR #96.

## 10. Brand system requirements

The customer experience should be coherent across website, PDF, email and dashboard.

Define before public launch:

- logo/wordmark usage rules;
- typography and accessibility minimums;
- color/status semantics for bullish/bearish/wait/data error without relying on color alone;
- chart/table readability rules;
- date/version/source conventions;
- voice: disciplined, probabilistic, evidence-led, no sensationalism;
- risk/disclosure placement;
- consistent names for Alpha Score, regime, rotation, setup, option state, portfolio action and DATA ERROR.

## 11. Launch scorecard

Public commercial beta remains **NO-LAUNCH** if any required gate is missing.

### Product

- [ ] Tier promise, inclusions and exclusions approved.
- [ ] Sample report is readable and representative.
- [ ] Onboarding and first-week activation are tested.
- [ ] Cancellation/reactivation/support flows are documented.

### Technical / operations

- [ ] Identity and server-side entitlements pass #85.
- [ ] Billing replay/reconciliation passes #85.
- [ ] Customer delivery SLO/readiness evidence passes #87.
- [ ] Restore and incident evidence exists under #87.
- [ ] Security/privacy launch evidence passes #103.

### Evidence / legal

- [ ] Performance/claim evidence gate passes #86.
- [ ] Required disclosures/risk materials are externally reviewed under #97.
- [ ] Planned product scope matches the scope actually reviewed.

### Commercial

- [ ] Pricing downside/base/upside economics are modeled.
- [ ] Funnel event schema is implemented with privacy minimization.
- [ ] Support ownership and capacity are defined.
- [ ] Launch acquisition experiments have cost caps and stop conditions.
- [ ] Rollback / pause-new-signups procedure exists.

### Trading boundary

- [ ] Customer research beta cannot enable live brokerage execution.

## 12. Metrics dashboard after beta starts

Evaluate product health separately from trading-model performance.

### Acquisition

- qualified traffic;
- sample engagement;
- account-create conversion;
- subscription conversion;
- customer acquisition cost when paid acquisition exists.

### Activation

- first-report open rate;
- first-week activation rate;
- time to first successful value event;
- delivery/access failure rate.

### Retention

- 30/60/90-day retention when sample size permits;
- voluntary/involuntary churn;
- reason-coded cancellation;
- reactivation rate;
- report engagement by cohort.

### Reliability

- scheduled delivery success/timeliness;
- stale/data-error frequency;
- authentication/entitlement failure;
- support incident frequency and time to resolution.

### Research quality

Research performance metrics remain governed separately by #86 and must not be mixed with product retention/conversion metrics.

## 13. Explicit decisions deferred for approval

- public brand/website copy;
- final logo/visual identity;
- public pricing;
- trial length/discounts;
- payment and identity vendors;
- public launch date;
- paid advertising budget;
- prospect/customer outreach;
- testimonials/referrals;
- institutional/enterprise tier;
- brokerage connectivity;
- public performance claims.

## 14. Definition of done for internal GTM readiness

This workstream is ready for an approval checkpoint when:

1. the product category, audience, promise and exclusions are coherent;
2. website information architecture and sample-product requirements are complete;
3. pricing hypotheses and unit-economics model inputs are defined;
4. acquisition/activation/retention events are specified;
5. all proposed trust/performance claims are either evidence-linked or removed;
6. launch gates connect #85, #86, #87, #97 and #103;
7. nothing has been publicly published, sold or promised without approval.
