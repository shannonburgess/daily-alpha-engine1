# Sector Residual Momentum Research V1

## Purpose

This research-only diagnostic implements the first safe engineering slice of quant challenger #156. It decomposes a **pre-qualified** stock candidate's momentum into:

- sector/common momentum, measured from the mapped **1x** sector proxy; and
- stock-specific residual momentum, measured as stock return minus sector-proxy return.

It is designed to answer a research question before any instrument-expression experiment:

> Is the candidate's momentum primarily stock-specific, or is it mostly riding sector beta?

The module is intentionally disconnected from PAPER/live execution. It cannot authorize an entry, mutate a portfolio, choose a leveraged ETF, select an option, change TradingView, or enable trading.

## Frozen first-pass semantics

V1 intentionally uses a transparent arithmetic residual rather than a fitted regression:

`residual_horizon = stock_return_horizon - sector_proxy_return_horizon`

The weighted composite uses the pre-registered horizons:

- 20D: 50%
- 63D: 30%
- 126D: 20%

The first pass keeps the underlying R2 candidate rules frozen. Residual momentum is evaluated **after** a candidate already qualifies; it does not alter breakout, ADX, efficiency, RSI, close-location, earnings, liquidity, portfolio-risk, or exit rules.

Only unlevered 1x sector proxies are valid signal inputs. 2x/3x sector ETFs remain separate research execution vehicles and cannot feed the residual signal.

## Point-in-time contract

Every observation carries both `as_of` and `known_at` timestamps. The analyzer rejects any input whose data or knowledge timestamp is later than the requested decision boundary.

Other fail-closed rules:

- non-finite returns are rejected;
- blank security/sector/industry/proxy identities are rejected;
- `known_at < as_of` is rejected;
- conflicting duplicates for the same permanent security ID are rejected;
- an identical duplicate is idempotent;
- a leveraged sector proxy is rejected.

## Cross-sectional attribution

For each decision boundary, the analyzer computes:

- 20D / 63D / 126D residual returns;
- weighted residual score;
- weighted sector score;
- number of positive residual horizons;
- deterministic within-sector residual percentile; and
- deterministic within-industry residual percentile.

Percentiles use average ranks for ties and are input-order independent. A one-name sector/industry cohort receives percentile `1.0`; it should be interpreted as **no peer dispersion available**, not as proof of exceptional alpha.

## Research classes

The output classes are descriptive research labels only:

- `STOCK_SPECIFIC_LEADER` — positive residual at all three horizons and at/above the 65th within-sector percentile;
- `POSITIVE_RESIDUAL` — positive composite residual at/above the 50th within-sector percentile;
- `MIXED` — positive composite residual but below the confirmation percentile;
- `SECTOR_BETA_DOMINANT` — non-positive composite residual while the sector composite is positive;
- `NEGATIVE_RESIDUAL` — non-positive composite residual and non-positive sector composite.

These labels do **not** map to BUY/SELL/WAIT, position size, sector-ETF substitution, option selection, or any execution instruction.

## Required next empirical step

V1 is an instrumentation layer, not evidence that the hypothesis works. The next research stage should consume historical point-in-time qualified R2 candidates and compare the frozen challengers from #156:

1. canonical R2 control;
2. residual score > 0 confirmation;
3. within-sector residual percentile >= 50th;
4. within-sector residual percentile >= 65th;
5. residual score as tie-break/ranking only;
6. research-only `SECTOR_BETA_DOMINANT` classification for later stock-vs-sector expression comparison.

The evaluation must keep 2022-2024 development, 2025 validation, and 2026 YTD stress separate and report sector/industry attribution, turnover, concentration, beta, capacity and top-trade exclusions.

Regression-based market + sector residuals remain a separate second-stage experiment. Do not silently replace this V1 arithmetic residual after observing outcomes.

## Promotion boundary

No PAPER/live behavior may change from this module. Promotion requires out-of-sample evidence under the #156 hurdle and a separate reviewed change. The immutable safety fields remain:

- `research_only=true`
- `paper_entry_authorized=false`
- `portfolio_mutation_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`
