# Daily Alpha Performance Methodology Contract v1

Status: internal commercial-beta readiness draft. This document and the accompanying code do not authorize public performance claims, customer launch, live trading, or legal/compliance conclusions.

## Purpose

Daily Alpha needs one versioned calculation/evidence contract before any customer-visible performance statistic can be published. The contract prevents silent mixing of performance bases, benchmark switching, stale option marks, revised-data overwrites, and unversioned cost assumptions.

## Non-mixable performance bases

- `ACTUAL`: only confirmed executed real-capital fills, if separately authorized in the future.
- `PAPER`: prospective paper-account fills under the documented paper rules.
- `BACKTEST`: historical simulation under point-in-time/versioned assumptions.
- `HYPOTHETICAL`: scenarios that do not qualify as actual, paper, or canonical backtest evidence.

One customer-visible performance artifact must use exactly one basis. Cross-basis comparison may be shown only as separately labeled series, never aggregated into one return line.

## Benchmark policy

A benchmark identity/version is frozen before the evaluation period or before a customer claim is generated. Changing the benchmark requires a new methodology/claim version; historical evidence is not silently restated to a more favorable comparator.

The initial equity-research reference may use a broad U.S. equity total-return benchmark, while sector/event sleeves may define additional predeclared comparators. Benchmark choice must reflect the mandate and risk exposure rather than retroactive best fit.

## Return and valuation policy

Every evidence artifact carries:
- methodology version;
- strategy/model version;
- start/end timestamps;
- valuation cutoff;
- source-data cutoff;
- benchmark ID/version;
- gross return;
- net return;
- cost-evidence basis;
- evidence hash.

Annualization is prohibited until the minimum period defined by the methodology version is satisfied. Daily NAV, deposits/withdrawals, realized/unrealized P&L, partial exits, adds, rolls, assignments and multi-leg structures require separate deterministic calculation fixtures before customer use.

## Transaction-cost policy

Stocks/ETFs require explicit commission/fee and slippage/implementation-shortfall assumptions. When those costs are estimated rather than observed, gross and net results must remain separately visible.

Long-option research requires executable-side marks by default:
- entry: observed ask;
- exit/roll close: observed bid;
- stale, locked, crossed or missing quotes: fail closed for customer performance evidence.

No customer-facing option result may silently substitute mid, last, theoretical value, or an asynchronous quote when executable bid/ask evidence is required.

## Point-in-time and revision policy

- revised upstream data cannot overwrite the decision-time observation;
- universe membership should be point-in-time where feasible and limitations must be disclosed;
- delisted/failed securities remain in historical cohorts;
- methodology changes create a new version and trigger claim revalidation;
- evidence hashes and provenance manifests connect the statistic to immutable source/calc history.

## Initial fail-closed gates implemented in code

`src/daily_alpha/performance_methodology.py` currently rejects:
- mixed ACTUAL/PAPER/BACKTEST/HYPOTHETICAL evidence;
- methodology-version mismatch;
- benchmark mismatch;
- non-executable option quote quality when executable-side marking is required;
- estimated costs that are not reflected in net return.

The module also produces a deterministic methodology hash for provenance/versioning.

## Still required before commercial beta

1. Canonical daily NAV calculator and fixtures for stock, ETF, long option, short premium, add/partial/exit and roll events.
2. Benchmark registry with historical total-return source lineage.
3. Transaction-cost registry tied to observed paper execution where available.
4. Minimum sample/period policy for win rate, expectancy, Sharpe/Sortino/Calmar and annualization.
5. Methodology-change invalidation hook into the performance-claim registry from #86 / PR #96.
6. Provenance manifest linkage from #116.
7. Customer-channel disclosure mapping.
8. External legal/compliance review under #97 before any public use.

Tracks #81, #86, #97, #113 and #116.
