# Daily Alpha Quant Platform Expansion Roadmap

Updated: 2026-08-18 Pacific Time

## Purpose

Extend Daily Alpha from a strong systematic momentum/options/catalyst platform into a broader multi-strategy quantitative investment platform while preserving the existing research/paper-only boundary, deterministic execution controls, evidence-gated promotion, and live-trading lockout.

These initiatives are additive. None may bypass the canonical signal, risk, instrument-quality, execution, audit, or model-governance controls already in the platform.

## Expansion priorities

### 1. Factor Attribution Engine

Goal: formalize the existing signal stack into named, measurable factors and determine which factors actually add out-of-sample alpha.

Initial factor families:
- momentum / trend persistence;
- relative strength;
- volatility / trendability;
- liquidity / capacity;
- sector and industry leadership;
- quality and fundamental robustness when point-in-time data is available;
- value / valuation context when point-in-time data is available;
- options-implied volatility, skew and term structure;
- event / catalyst state;
- breadth and market regime.

Required outputs:
- per-candidate factor vector;
- factor contribution to rank/decision;
- rolling information coefficient and hit-rate by factor;
- factor decay by horizon;
- factor correlation / redundancy matrix;
- performance by regime, sector, industry and market-cap/liquidity bucket;
- explicit factor-removal tests to prove incremental value.

Promotion gate: no factor receives more capital or ranking weight solely because it improves in-sample return. Require point-in-time data, walk-forward stability, realistic costs and outlier-exclusion tests.

### 2. Strategy Forensics & Model Health Engine

Goal: make Daily Alpha continuously challenge its own decisions instead of relying on manual chart review to discover missed opportunities or model decay.

Required diagnostics:
- missed breakout followed by favorable trend;
- delay from first actionable breakout to actual entry;
- WAIT reason attribution by bar;
- maximum favorable excursion / maximum adverse excursion in R;
- percent of MFE captured;
- exit then re-entry at a worse price;
- churn / turnover caused by individual exits or filters;
- missed winners and false starts by reason code;
- v2.4/v2.5 and future champion/challenger disagreement ledger;
- rolling expectancy, profit factor, Sharpe/Sortino and drawdown drift;
- parameter sensitivity and feature stability;
- alert / strategy / paper-ledger state mismatch detection.

Required model-health states:
- HEALTHY;
- WATCH;
- DEGRADED;
- DATA_ERROR;
- REVIEW_REQUIRED.

Promotion/demotion gate: model-health deterioration can reduce research confidence or trigger review, but no automated live-capital action is permitted.

### 3. Portfolio Risk-Contribution Engine

Goal: move beyond fixed-dollar/fixed-risk sizing toward institutional portfolio construction based on marginal risk contribution, covariance and capacity.

Research components:
- realized-volatility targeting;
- shrinkage covariance matrix;
- marginal and component contribution to portfolio volatility;
- beta, delta, gamma, vega and theta contribution where applicable;
- sector / industry / thematic cluster contribution;
- correlation-cluster concentration;
- liquidity-adjusted risk;
- dynamic gross/net exposure budgets;
- risk-budget comparison against equal-risk and fixed-NAV sizing.

Required tests:
- covariance estimation stability;
- correlation shock toward 1.0;
- concentration and liquidity stress;
- capacity at increasing NAV tiers;
- comparison of CAGR, Sharpe/Sortino, Calmar, max drawdown and turnover against the canonical portfolio.

Promotion gate: risk allocation must improve portfolio efficiency without hiding leverage, concentration, liquidity or tail risk.

### 4. Relative Value / Statistical Arbitrage Engine

Goal: add an independent, lower-directional-beta alpha family rather than relying entirely on momentum/trend/catalyst returns.

Research sleeves:
- stock versus sector ETF residual momentum / mean reversion;
- stock versus peer-group residuals;
- pair spread / cointegration research;
- ETF versus constituent-basket divergence;
- industry-neutral cross-sectional relative value;
- volatility-relative-value and skew/term-structure divergence after historical option data is sufficiently reliable.

Required controls:
- point-in-time universe membership;
- hedge-ratio stability;
- cointegration / spread-stability testing where used;
- borrow/short availability and realistic financing assumptions before any short implementation study;
- transaction costs and turnover;
- crowding/capacity diagnostics;
- beta and factor-neutrality attribution.

Promotion gate: relative-value research must show incremental portfolio diversification and positive net expectancy after realistic implementation costs. It remains research-only until a separately approved paper framework exists.

### 5. Stress & Tail-Risk Engine

Goal: quantify how the platform behaves under market states that are poorly represented by ordinary backtests.

Scenario library:
- volatility doubling / volatility-of-volatility shock;
- equity correlation converging toward 1.0;
- broad overnight gap down;
- sector-specific gap shock;
- 2020-style liquidity shock;
- 2022-style rate shock;
- options bid/ask spread widening;
- IV crush after event exposure;
- index drawdown with simultaneous factor reversal;
- Treasury/equity correlation regime change;
- stale-data or market-data interruption during open risk;
- market halt / delayed reopen scenarios.

Required outputs:
- stressed NAV and drawdown;
- stressed beta/Greeks;
- liquidity-to-exit and implementation shortfall;
- concentration contribution to loss;
- hedge effectiveness and hedge cost;
- recovery time;
- probability-of-ruin / Monte Carlo sequence diagnostics where appropriate.

Promotion gate: defensive overlays must improve tail behavior without an unacceptable long-run return, turnover or carry penalty.

### 6. Implementation Cost & Market-Impact Engine

Goal: measure alpha after realistic execution rather than treating quoted or theoretical edge as investable edge.

Required components:
- bid/ask spread cost;
- intended-limit versus realized-fill slippage;
- commissions/fees;
- option contract multiplier and quantity effects;
- participation rate versus volume/open interest;
- underlying ADV and dollar-ADV participation;
- estimated market impact / implementation shortfall by NAV tier;
- missed-fill and partial-fill treatment;
- turnover drag;
- capacity decay of strategy expectancy.

Required outputs:
- gross alpha versus net alpha;
- implementation-cost attribution per trade and strategy;
- capacity curve by $1M / $5M / $10M / $25M / $50M / $100M+ research NAV tiers;
- instrument-expression comparison after costs.

Promotion gate: no strategy is considered scalable based on gross backtest returns alone.

### 7. Machine-Learning Meta-Ranker

Goal: use ML initially as a challenger/meta-model that ranks or calibrates deterministic opportunities rather than replacing the canonical rules engine.

Initial prediction target examples:
- probability of positive expectancy;
- probability of reaching +1R/+2R/+3R before stop;
- expected R distribution;
- probability a WAIT state becomes ENTRY_READY within N bars;
- probability of failed breakout;
- expected MFE capture under alternative exit policies.

Candidate features:
- Pine state and lifecycle;
- OVTLYR status/trajectory;
- sector and industry state;
- relative strength;
- ADX, efficiency and RSI;
- breadth and dispersion;
- volatility regime;
- ORATS IV/skew/term structure;
- unusual options flow;
- catalyst/event state;
- liquidity/capacity;
- portfolio correlation and marginal risk contribution.

Governance:
- point-in-time feature store;
- strict train/validation/holdout separation;
- frozen feature definitions and model hashes;
- calibration and Brier/log-loss diagnostics where applicable;
- feature importance/stability and ablation tests;
- no leakage from future labels or revised fundamentals;
- comparison against simple linear/logistic baselines;
- explicit overfitting / data-snooping controls;
- champion/challenger shadow scoring before any use in sizing or execution.

Promotion gate: ML may initially influence research ranking only. It cannot authorize trades or override deterministic risk gates without a separate evidence and governance approval.

### 8. Cross-Asset Regime Engine

Goal: improve regime awareness and portfolio hedging by observing multiple liquid asset classes rather than equity price action alone.

Initial research universe:
- broad U.S. equity indexes;
- sector ETFs;
- Treasury duration / short-rate proxies;
- gold and silver;
- commodities / energy proxies;
- volatility indexes or liquid volatility proxies when data rights permit;
- U.S. dollar / currency proxies;
- credit-spread proxies;
- optional crypto regime inputs only if point-in-time, reliable and demonstrably incremental.

Required regime features:
- trend state;
- realized volatility;
- cross-asset correlation;
- risk-on/risk-off breadth;
- rates/curve state;
- commodity/inflation pressure;
- credit stress;
- dispersion/concentration.

Promotion gate: cross-asset variables must add incremental predictive or risk-control value beyond the existing equity trend/volatility/breadth state. No macro label is allowed to use hindsight.

## Integration sequence

Recommended build order:
1. Factor Attribution Engine.
2. Strategy Forensics & Model Health.
3. Portfolio Risk-Contribution Engine.
4. Relative Value / Statistical Arbitrage Engine.
5. Stress & Tail-Risk Engine.
6. Implementation Cost & Market-Impact Engine.
7. Machine-Learning Meta-Ranker.
8. Cross-Asset Regime Engine.

The order is deliberate: create clean labeled factor, execution and model-health data before training an ML meta-model, and build portfolio/cost controls before promoting additional alpha engines.

## Shared evidence standard

Every expansion initiative must include:
- a written, falsifiable hypothesis;
- versioned code/configuration and immutable experiment identity;
- point-in-time data and no-lookahead controls;
- explicit DATA_ERROR behavior;
- train/validation/holdout or equivalent walk-forward design;
- realistic transaction cost, liquidity and capacity assumptions;
- benchmark and canonical-strategy comparison;
- results by regime/sector/industry where relevant;
- best-trade/outlier exclusion;
- parameter/feature stability checks;
- a null/kill criterion;
- no automatic promotion into paper/live execution.

## Platform boundary

These roadmap items are research and platform-development initiatives. They do not authorize live trading, capital deployment, leverage, customer-specific advice, brokerage integration, or automatic model promotion. `trading_authorized=false` and `live_trading_enabled=false` remain the operating boundary until a separate future approval process explicitly changes them.
