# Daily Alpha Commercial Beta Product Spec

Status: internal planning only. No pricing is published, no customer invitations are authorized, and no feature described here enables personalized fiduciary advice or autonomous execution.

Tracks: #81 and #88. Entitlement implementation should remain compatible with #85 / PR #91.

## First beta customer

The first beta should target a self-directed, market-engaged investor or trader who wants an institutional-style daily research process but remains responsible for investment decisions and execution.

The job to be done is: **compress a large amount of market, sector, catalyst, options and risk information into a disciplined daily decision framework with an auditable history.**

The beta should not try to serve every investor type or simulate a separately managed account.

## Product principles

1. Research first; autonomous execution is excluded.
2. Explain the evidence behind rankings and risk states instead of publishing unexplained scores.
3. Separate actual, paper, backtest and hypothetical performance at all times.
4. Prefer a small number of clear tiers over feature sprawl.
5. Make data freshness and unavailable-data states visible.
6. Let a customer understand the day's posture and Top 3 in under one session, with deeper detail available when wanted.
7. Preserve an immutable dated archive so customers can evaluate consistency rather than only today's winners.

## Proposed beta tier architecture

These are internal feature definitions only; pricing remains a later approval decision.

### RESEARCH

**Promise:** A disciplined morning-to-evening Daily Alpha research process that identifies market regime, rotation, high-conviction opportunities and defined risk without requiring the customer to build the analysis stack.

Included entitlements:

- `MORNING_NOTE`
- `EVENING_BRIEF`
- market regime and risk posture
- sector / industry / theme rotation
- Top 3 actionable research setups with ENTER / WAIT / CANCEL state
- earnings and major catalyst flags
- concise methodology/explainability pages
- immutable dated report archive
- performance-evidence page with clearly separated paper/backtest/hypothetical categories

Explicitly excluded:

- full ranked research universe/export;
- advanced quant diagnostic dashboard;
- individualized portfolio advice;
- brokerage connection or order routing;
- autonomous alerts that place trades.

### RESEARCH_PLUS

**Promise:** The full Daily Alpha research workbench for customers who want to investigate the ranked opportunity set, quant diagnostics and historical decision evidence behind the daily executive brief.

Includes everything in RESEARCH plus:

- `QUANT_DASHBOARD`
- full ranked research shortlist/watchlist
- candidate state changes and rotation lifecycle detail
- quant/research challenger diagnostics when production-ready
- deeper options positioning and volatility diagnostics when reliable data is available
- rejected/tracked research ledger for learning what the model intentionally passed
- downloadable customer-safe research exports where licensing permits
- expanded methodology/version history and historical decision search

Explicitly excluded:

- individualized allocation or fiduciary recommendations;
- live brokerage execution;
- customer-specific automated trading rules;
- any data redistribution not permitted by upstream licenses.

## Onboarding journey

### Step 1 — Account creation

- create immutable customer ID;
- verify email/account ownership;
- apply authentication/session controls;
- never store payment-card data in Daily Alpha unless a separately reviewed architecture explicitly requires it.

### Step 2 — Required acknowledgments

Before research access:

- display current product disclosures and version;
- record acknowledgement timestamp/version;
- clearly state research/subscription boundary and performance-basis labels;
- preserve external legal/compliance review reference required by launch gate.

### Step 3 — Preferences

Collect only low-sensitivity product preferences needed for delivery, such as:

- morning/evening delivery preference;
- timezone/display preference;
- report-format preference;
- optional sectors/themes to follow for navigation only.

Do not convert preferences into personalized suitability or discretionary portfolio management during the beta.

### Step 4 — First-session orientation

Show a short guided explanation of:

- market regime;
- rotation lifecycle;
- Alpha/ranking evidence;
- ENTER / WAIT / CANCEL semantics;
- earnings/event states;
- option vs stock instrument-selection logic;
- data-unavailable/fail-closed labels;
- actual vs paper vs backtest vs hypothetical performance.

### Step 5 — Activation

Activation is achieved when the customer successfully accesses the first scheduled research report and can navigate to the methodology/performance-evidence page. Report opening alone should not be treated as evidence that the customer understands the methodology.

## First-week experience

- Day 0: welcome/orientation + latest report.
- Day 1: morning note + evening brief with brief explanation of what changed.
- Day 2–3: surface rotation and candidate-state history so the product feels like a process, not a tip sheet.
- Day 4–5: invite structured product feedback inside the product/support flow; do not solicit public testimonials as part of the beta without separate review.

## Support model

Initial support categories:

- ACCOUNT_ACCESS
- ENTITLEMENT_OR_BILLING_STATE
- REPORT_DELIVERY
- DATA_OR_TIMESTAMP_QUESTION
- METHODOLOGY_QUESTION
- PERFORMANCE_EVIDENCE_QUESTION
- TECHNICAL_BUG
- FEATURE_REQUEST
- COMPLIANCE_OR_DISCLOSURE_ESCALATION

Every support item should have customer ID, category, created timestamp, severity and resolution state. Sensitive data should not be requested unless needed.

## Cancellation and reactivation

- cancellation should have an explicit effective date and entitlement outcome;
- billing and entitlement states must reconcile idempotently;
- canceled/expired/past-due accounts fail closed under the control plane;
- reactivation should create an auditable billing/account event, not an undocumented admin toggle;
- historical customer records should follow the eventual approved retention/deletion policy.

## Product analytics with privacy minimization

Beta metrics should focus on whether the product works rather than collecting broad behavioral surveillance.

Core operational/product metrics:

- signup → disclosure acknowledgement conversion;
- first-report activation rate;
- scheduled delivery success/failure;
- weekly active report users;
- methodology/explainability usage;
- archive/history usage;
- support rate by category;
- voluntary feedback tags;
- tier changes/cancellations/reactivations;
- retention/churn once sample size is meaningful.

Do not collect brokerage credentials, portfolio holdings, precise financial profile, or unrelated behavioral data merely for analytics.

## Feedback loop

Every beta feedback item should be tagged as one of:

- PROBLEM
- CONFUSING
- MISSING_DATA
- FEATURE_REQUEST
- TRUST_EVIDENCE
- DELIVERY
- PERFORMANCE_PRESENTATION
- SUPPORT

Product decisions should preserve a short decision log: feedback count/sample, affected workflow, proposed change, expected benefit, risk, owner and final disposition. Avoid allowing one vocal customer to redefine the strategy without broader evidence.

## Beta launch/no-launch product gates

NO-GO unless:

1. each tier's entitlements are enforced server-side and isolation tests pass;
2. onboarding disclosures and acknowledgement versions are auditable;
3. a first-time customer can understand the core report without a live walkthrough;
4. cancellation/reactivation/support flows are documented and testable;
5. scheduled delivery reliability evidence exists;
6. performance evidence cannot mix actual, paper, backtest or hypothetical bases;
7. data freshness and unavailable states are visible;
8. customer analytics are privacy-minimized;
9. external legal/compliance review is complete for the actual beta scope;
10. live brokerage execution remains disabled.

## Decisions intentionally deferred

- public pricing;
- free-trial duration;
- payment vendor;
- identity vendor;
- public website copy;
- testimonial/referral program;
- institutional/enterprise tier;
- brokerage integration;
- personalized portfolio functionality.

Those decisions should follow evidence from staging and beta readiness rather than be hard-coded prematurely.
