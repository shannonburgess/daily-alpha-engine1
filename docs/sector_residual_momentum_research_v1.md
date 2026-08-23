# Sector Residual Momentum Research V1

## Purpose

This research-only diagnostic implements the first safe engineering slices of quant challenger #156. It decomposes a **pre-qualified** stock candidate's momentum into:

- sector/common momentum, measured from the mapped **1x** sector proxy;
- stock-specific arithmetic residual momentum, measured as stock return minus sector-proxy return; and
- separately reported market-beta and sector+market regression residual diagnostics calibrated only from trailing point-in-time returns supplied by the research harness.

It is designed to answer a research question before any instrument-expression experiment:

> Is the candidate's momentum primarily stock-specific, or is it mostly riding sector/market beta?

The modules are intentionally disconnected from PAPER/live execution. They cannot authorize an entry, mutate a portfolio, choose a leveraged ETF, select an option, change TradingView, or enable trading.

## Frozen first-pass arithmetic semantics

The primary V1 challenger intentionally keeps a transparent arithmetic residual rather than silently replacing it with a fitted model:

`residual_horizon = stock_return_horizon - sector_proxy_return_horizon`

The weighted composite uses the pre-registered horizons:

- 20D: 50%
- 63D: 30%
- 126D: 20%

The first pass keeps the underlying R2 candidate rules frozen. Residual momentum is evaluated **after** a candidate already qualifies; it does not alter breakout, ADX, efficiency, RSI, close-location, earnings, liquidity, portfolio-risk, or exit rules.

Only unlevered 1x sector proxies are valid signal inputs. 2x/3x sector ETFs remain separate research execution vehicles and cannot feed the residual signal.

## Regression diagnostic slice

A separate `sector_residual_regression` module implements two additional #156 feature families without replacing the arithmetic control/challengers:

- trailing market beta estimated from stock and SPY-period returns;
- trailing joint market + mapped-sector betas estimated from stock, SPY and the 1x sector proxy;
- 20D / 63D / 126D beta-adjusted residual returns using those frozen trailing betas; and
- positive weekly residual fractions for both the market-only and joint factor models.

The caller supplies the trailing calibration window explicitly. The module does not search a window length, optimize a threshold, or promote a variant. Regression calibration fails closed when market variance is singular or the market/sector covariance matrix cannot identify separate factor loadings. The joint model uses an intercept for weekly calibration residuals; horizon residual momentum remains the transparent beta-adjusted return `stock - beta_market*market - beta_sector*sector` so no arbitrary alpha-period compounding assumption is introduced.

## Point-in-time contract

Every observation carries both `as_of` and `known_at` timestamps. The analyzers reject any input whose data or knowledge timestamp is later than the requested decision boundary.

Other fail-closed rules:

- non-finite returns are rejected;
- blank security/sector/industry/proxy identities are rejected;
- `known_at < as_of` is rejected;
- conflicting duplicates for the same permanent security ID are rejected in the cross-sectional analyzer;
- an identical duplicate is idempotent in the cross-sectional analyzer;
- regression calibration periods must be ordered, unique and known by the decision boundary;
- singular regression factor inputs are rejected rather than regularized silently; and
- a leveraged sector proxy is rejected.

## Cross-sectional attribution

For each decision boundary, the arithmetic analyzer computes:

- 20D / 63D / 126D residual returns;
- weighted residual score;
- weighted sector score;
- number of positive residual horizons;
- deterministic within-sector residual percentile; and
- deterministic within-industry residual percentile.

Percentiles use average ranks for ties and are input-order independent. A one-name sector/industry cohort receives percentile `1.0`; it should be interpreted as **no peer dispersion available**, not as proof of exceptional alpha.

## Research classes

The arithmetic output classes are descriptive research labels only:

- `STOCK_SPECIFIC_LEADER` — positive residual at all three horizons and at/above the 65th within-sector percentile;
- `POSITIVE_RESIDUAL` — positive composite residual at/above the 50th within-sector percentile;
- `MIXED` — positive composite residual but below the confirmation percentile;
- `SECTOR_BETA_DOMINANT` — non-positive composite residual while the sector composite is positive;
- `NEGATIVE_RESIDUAL` — non-positive composite residual and non-positive sector composite.

These labels do **not** map to BUY/SELL/WAIT, position size, sector-ETF substitution, option selection, or any execution instruction.

## Pre-registered variants

The frozen first-pass selector helpers compare only already-qualified R2 candidates:

1. canonical R2 control;
2. arithmetic residual score > 0 confirmation;
3. within-sector arithmetic residual percentile >= 50th;
4. within-sector arithmetic residual percentile >= 65th;
5. arithmetic residual score as tie-break/ranking only; and
6. research-only `SECTOR_BETA_DOMINANT` classification for later stock-vs-sector expression comparison.

The market-only and joint regression residuals are additional diagnostic features for the pre-registered empirical study. They are not silently combined with the frozen inclusion thresholds above.

## Required empirical step

These modules are instrumentation, not evidence that the hypothesis works. The historical point-in-time evaluation must keep 2022-2024 development, 2025 validation, and 2026 YTD stress separate and report:

- CAGR, volatility, Sharpe, Sortino, Calmar and drawdown/recovery metrics;
- R expectancy, profit factor, average win/loss and win rate;
- sector concentration and marginal risk contribution;
- beta to SPY and the mapped sector ETF;
- turnover / replacement churn;
- stock-vs-sector relative performance after costs;
- held-out-symbol results;
- top-1/top-5 trade exclusions and by-sector results; and
- capacity at the pre-registered capital tiers when implementation data permits.

Do not optimize a large threshold/window grid after observing outcomes. Regression stability and incremental information versus the existing relative-strength/sector-rotation stack must be measured explicitly.

## Promotion boundary

No PAPER/live behavior may change from these modules. Promotion requires out-of-sample evidence under the #156 hurdle and a separate reviewed change. The immutable safety fields remain:

- `research_only=true`
- `paper_entry_authorized=false`
- `portfolio_mutation_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`
