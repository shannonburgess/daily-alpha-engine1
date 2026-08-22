# Daily Alpha Institutional Portfolio Construction V1

## Purpose

Portfolio Construction translates security-level CIO investment intents into a portfolio-level allocation **proposal**.

The core question is not:

> Is this security attractive?

It is:

> Is this the best use of the next unit of portfolio risk relative to every existing position and competing opportunity?

This layer remains below the independent deterministic Risk Governor.

## Authority hierarchy

```text
Governance Lock
      ↓
Independent Deterministic Risk Governor
      ↓
Portfolio Construction
      ↓
CIO / Fusion
      ↓
Research Council + Quant Models
```

Portfolio Construction can propose target weights. It cannot:

- authorize capital;
- approve risk;
- override the Risk Governor;
- override Governance;
- place orders;
- authorize execution;
- enable live trading.

## Inputs

### PortfolioSnapshot

Point-in-time account/portfolio state with:

- NAV;
- cash weight;
- current position weights;
- sector identity;
- annualized volatility estimates;
- factor exposures;
- immutable source lineage.

V1 is a long-only reference allocator. A dedicated hedge sleeve is intentionally not silently forced into this engine.

### CIOInvestmentDecision

Each opportunity must point to the exact CIO decision ID and action that produced it.

### OpportunityEstimate

Portfolio-construction forecasts are separate from CIO conviction. Each estimate carries:

- expected return in basis points;
- annualized volatility;
- forecast confidence;
- sector;
- liquidity/capacity weight;
- factor loadings;
- forecast-model identity/version;
- exact CIO decision lineage.

This prevents position size from being a simple function of `CIO conviction × NAV`.

### CorrelationSurface

The correlation matrix is point-in-time, symmetric, bounded, and positive semidefinite. Missing correlation coverage fails closed when it is required to evaluate marginal portfolio risk.

## Objective

The transparent V1 reference allocator evaluates marginal portfolio utility using:

- confidence-adjusted expected return contribution;
- change in portfolio variance;
- risk-aversion penalty;
- turnover penalty;
- concentration penalty;
- position headroom;
- sector headroom;
- factor headroom;
- liquidity/capacity headroom;
- minimum cash reserve.

The reference objective is intentionally simple and auditable. A future convex/QP or other optimizer can implement the same contracts and compete against V1 under model governance rather than replacing it invisibly.

## CIO action semantics

- `BUY` / `ADD`: eligible for positive marginal-risk allocation when utility is positive and construction headroom exists.
- `WAIT` / `NO_ACTION`: no new allocation.
- `HOLD`: retain current weight unless another higher-authority layer later requires a change.
- `TRIM`: reduce an existing position according to the versioned construction policy before considering new risk.
- `SELL`: target zero in the construction proposal.
- `HEDGE`: V1 emits an explicit warning because hedging belongs in a dedicated multi-asset/hedge sleeve rather than being approximated as a long-only equity allocation.

## Marginal assessment

Every risk-on increment records:

- current and proposed weight;
- expected-return contribution;
- portfolio volatility before/after;
- marginal variance;
- weighted correlation to the existing portfolio;
- sector exposure after the increment;
- marginal utility;
- blockers and warnings.

This allows future forensics to answer why one security received the next unit of risk instead of another.

## Allocation proposal

`PortfolioAllocationProposal` records:

- current-to-target weights;
- target cash;
- expected portfolio volatility;
- estimated turnover;
- objective utility;
- selected marginal assessments;
- excluded opportunities;
- deterministic proposal ID.

All authority flags remain false:

- capital allocation authorization;
- Risk Governor authorization;
- execution authorization;
- trading authorization;
- live trading.

## Separation from the Risk Governor

Portfolio-construction constraints are optimization constraints. They help construct a sensible proposal, but they are not the final capital-protection authority.

The next layer must independently re-evaluate the proposal against hard portfolio rules, drawdown state, concentration, liquidity, event exposure, tail-risk/stress limits, account state, and governance locks.

A high portfolio-construction utility score can never bypass a Risk Governor rejection.
