# Convex Ridge Fund-Readiness Roadmap

## Purpose

Daily Alpha is being built as the quantitative research and operating system that could ultimately support **Convex Ridge Capital**. **Daily Alpha Research** remains a useful optional distribution and early-revenue channel, but it is not the required end-state.

This document is an internal engineering and operating roadmap. It does not authorize fund formation, investment-adviser activity, fundraising, customer launch, live trading, brokerage connectivity, or deployment of real capital.

## Brand and operating architecture

- **Daily Alpha Labs** — parent research/technology company.
- **Convex Ridge Quantitative** — institutional quantitative research identity.
- **Daily Alpha / Daily Alpha Engine** — proprietary research, signal, portfolio and evidence platform.
- **Daily Alpha Research** — optional research/newsletter/distribution business.
- **Convex Ridge Capital** — reserved future investment-management/fund identity, subject to external legal and operational review.

## Preferred progression

### Stage 1 — Research system

Build and validate the investment process before capital scaling:

- point-in-time inputs and immutable histories;
- versioned strategy/model/methodology rules;
- reproducible backtests and sensitivity tests;
- ORATS and market-data reliability;
- portfolio risk, concentration, volatility and covariance research;
- capacity, turnover, implementation shortfall and liquidity analysis;
- instrument selection and stock fallback with fail-closed data handling.

### Stage 2 — Forward paper fund

Operate the paper portfolio as if it were an institutional mandate:

- frozen forward methodology cohorts;
- daily fund-style NAV and cash ledger;
- realized/unrealized P&L;
- gross/net exposure and concentration;
- benchmark/excess return;
- transaction-cost assumptions and option mark policy;
- attribution by strategy sleeve, symbol, sector and instrument;
- drawdown, turnover and capacity statistics;
- monthly scorecard with winners, losers, misses and best-trade exclusion;
- immutable evidence and report provenance.

The paper record must remain clearly labeled **PAPER** and must never be mixed with backtest, hypothetical or later actual performance.

### Stage 3 — Proprietary-capital readiness

No capital is deployed at this stage. Prove that an actual-execution path could operate safely:

- disabled-by-default brokerage adapter architecture;
- pre-trade risk and order validation;
- idempotent order state and kill/disable controls;
- fill capture and broker reconciliation;
- cash, buying power, assignment, expiration and corporate-action handling;
- actual fee/slippage/implementation-shortfall capture;
- daily NAV/accounting reconciliation and exception handling;
- staging incident, recovery and rollback drills;
- capacity/liquidity validation at the intended initial capital level;
- external tax/legal/operational checklist.

Promotion from paper to proprietary capital requires separate explicit user approval.

### Stage 4 — Proprietary live track record

If separately approved after the Stage 3 gates, track actual proprietary capital as a new evidence basis:

- `ACTUAL` fills and costs only;
- no backfilling or relabeling paper results as actual;
- same institutional NAV, attribution, benchmark, risk and provenance framework;
- strategy/version breaks preserved;
- real operational incidents and execution slippage included rather than normalized away.

### Stage 5 — Convex Ridge Capital institutional readiness

Before considering outside capital, obtain qualified external guidance and define the full operating model, including as applicable:

- adviser/fund/entity structure and regulatory perimeter;
- offering and fundraising rules;
- fund administrator, brokerage/custody, audit/tax and compliance requirements;
- valuation policy, including listed-option marks;
- investor reporting and books/records;
- allocation, conflicts, best-execution and proprietary/personal-trading policies;
- cybersecurity, BCP/DR and incident evidence;
- due-diligence data room;
- capacity frontier and strategy-level capital limits;
- investor communication and performance-marketing review gates.

No repository document is a legal conclusion or regulator approval.

### Stage 6 — Outside-capital launch

Only after explicit approval and all applicable legal, operational, evidence and service-provider gates are complete.

## Institutional performance architecture

The internal source of truth should be the **Convex Ridge Performance Ledger**. It must keep these bases separate:

- `ACTUAL`
- `PAPER`
- `BACKTEST`
- `HYPOTHETICAL`

Core outputs should include:

- NAV and period returns;
- benchmark and excess return;
- realized/unrealized P&L;
- gross/net exposure;
- drawdown and duration;
- volatility and risk-adjusted statistics only when sample rules permit;
- win rate, average winner/loser, expectancy, profit factor and R;
- turnover and implementation cost;
- attribution by strategy, sector, symbol and instrument;
- capacity/liquidity context;
- best-trade exclusion and concentration diagnostics;
- provenance/evidence hashes and methodology versions.

The public scorecard, if ever approved, must be a delayed/sanitized derivative of this ledger rather than an independent marketing calculation.

## Distribution and visibility

Daily Alpha should build recognition by publishing process and evidence rather than only successful outcomes. Candidate content franchises include:

- **Daily Alpha — What Changed Today**
- **The Convex Ridge Scorecard**
- **Daily Alpha Found Something We Should Test**
- research/methodology notes
- delayed case studies using the original timestamped decision and later outcome

Initially, any audience engine should generate drafts only. Public publishing, ads, prospect outreach, performance claims and fundraising remain separately approval-gated.

## Existing work to reuse

The fund path does not replace the existing engineering backlog. It increases the value of much of it:

- #86 / PR #96 / #113 — performance evidence, claims and canonical measurement methodology;
- #116 — reproducible provenance manifests;
- #75 / #106 / PR #95 / PR #110 — ORATS/data reliability;
- #92 / #105 / PR #109 — capacity and turnover-aware portfolio design;
- #114 / #115 — volatility and covariance/risk-contribution overlays;
- #87 / PR #100 / PR #111 — delivery, recovery and incident readiness;
- #103 / PR #104 — security/privacy and environment controls;
- #97 — external legal/regulatory review gate;
- #81 — commercial research-product optionality.

## New fund-readiness workstreams

- #118 — fund-readiness master roadmap;
- #119 — institutional performance ledger and fund-style NAV/attribution;
- #120 — proprietary-capital and institutional fund-operations readiness;
- #121 — public scorecard/audience engine as an optional distribution layer.

## Non-negotiable gates

Nothing in this roadmap authorizes:

- live trading;
- brokerage account connection;
- deployment of proprietary capital;
- outside fundraising or investor solicitation;
- formation or registration of any fund/adviser/entity;
- public performance advertising;
- paid customer launch;
- legal/compliance claims;
- production deployment.

Those actions require separate, explicit approval and the applicable evidence/external-review gates.