# Instrument Expression Research Plan

Status: **research only**. This document does not authorize paper/live changes.

## Purpose

Separate Daily Alpha's **alpha decision** from the instrument used to express it. The same point-in-time alpha state can be tested through shares, a long-dated call overlay, a leveraged sector proxy, or an SGOV treasury reserve without silently increasing the portfolio risk budget.

## Research hierarchy

1. A qualified individual R2 setup defaults to **shares** for long-duration trend capture.
2. A qualified individual setup may add a **long-dated call overlay** only when option quality and DTE gates pass. Stock and option risk must come from one common trade-risk budget.
3. If no individual stock qualifies but an unlevered sector signal is strong and constituent breadth confirms, test a **2x sector ETF**.
4. A **3x sector ETF** is a separate exceptional-strength experiment and must be explicitly enabled. It is never the default sector expression.
5. Unused unborrowed investable cash above an operational buffer is eligible for the **SGOV treasury reserve**.
6. Required-data errors always fail closed to **NO_TRADE / cash**. A dependency failure may not trigger a different instrument.

## Why the signal must come from the unlevered sector proxy

Daily-reset leveraged ETFs are implementation vehicles. Their multi-day return can diverge from a simple multiple of the underlying sector because leverage resets daily and the path of returns matters. The research signal therefore belongs to the unlevered sector/index proxy; 2x/3x products are tested only as expressions of the same signal.

## Initial option matrix

Compare:

- shares only;
- 70/30 risk-budget shares/long-call hybrid;
- long-call only when chain quality passes;
- 45–75 DTE control;
- 90–150 DTE long-duration candidate;
- no-roll versus systematic roll while the underlying R2 trend remains active.

Record option P&L separately from underlying-signal P&L and include bid/ask, theta, IV change, commissions, assignment/exercise handling assumptions, and roll cost.

## Initial sector matrix

For each strong sector state, hold the alpha signal constant and compare 1x / 2x / 3x expressions with risk-normalized sizing. Test 5-, 10-, 20- and 55-trading-day exits rather than assuming the stock-runner exit transfers to a daily-reset leveraged product.

Report volatility/compounding drag explicitly. Do not stack options on leveraged ETFs in the first experiment.

## SGOV reserve matrix

Compare true idle cash versus SGOV after preserving a fixed operational cash buffer. Never borrow or use margin merely to fund the reserve. Attribute reserve return separately from alpha and hedge P&L. If SGOV data is stale or unavailable, the model holds cash rather than substituting another product.

## Required metrics

- CAGR and total return;
- annualized volatility, Sharpe, Sortino and Calmar;
- maximum drawdown, drawdown duration and recovery time;
- average winner/loser, R expectancy and profit factor by expression;
- worst day/week/month/quarter;
- effective beta and sector concentration;
- option premium/IV/theta/spread/roll drag;
- leveraged-ETF path/volatility drag;
- SGOV reserve contribution;
- turnover and implementation cost;
- best-trade and top-five-winner exclusion;
- capacity at $1.25M, $25M, $50M and $100M NAV.

## Falsification

Kill an expression if its apparent improvement depends on one crash, one sector, or one outlier winner; if realistic costs erase the gain; if the common risk budget is exceeded; if stale data changes the instrument choice; or if leveraged/derivative implementation worsens long-horizon risk-adjusted compounding versus shares.

## Engineering boundary

`daily_alpha.instrument_expression_research` is deliberately disconnected from paper/live execution. Promotion requires a separate reviewed change and explicit user approval.

Tracks #142, #133, #127, #92 and #76.
