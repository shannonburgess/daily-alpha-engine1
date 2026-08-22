# Daily Alpha Deterministic Feature Store V1

## Purpose

Daily Alpha is a quantitative investment platform. Raw vendor payloads must not flow directly into investment agents or portfolio decisions. The Feature Store converts canonical market/event/research state into versioned, reproducible quantitative features with exact input lineage.

## Core principles

1. Canonical state first: features consume reconciled Daily Alpha state, not vendor-specific payloads.
2. Point-in-time only: no feature may consume a market state or bar beyond its explicit `as_of` boundary.
3. Versioned definitions: a feature key and version cannot be silently redefined.
4. Exact lineage: every feature value records the canonical input-state IDs used to compute it.
5. Explicit degradation: insufficient history produces `BLOCKED`; degraded but valid inputs propagate `WARNING`.
6. Immutable history: a logical feature observation cannot be rewritten in place with a different value.
7. Research-only foundation: Feature Store values cannot authorize trading or live execution.

## Feature definitions

`FeatureDefinition` records:

- feature key
- version
- calculator ID
- source family
- required lookback bars
- output unit
- whether the feature is core-required
- deterministic parameters
- deterministic definition ID

`FeatureRegistry` prevents a feature from changing semantics while retaining the same key/version.

## Feature values

`FeatureValue` records:

- permanent security ID
- feature key
- evaluation time
- exact definition ID/version
- output unit
- PASS / WARNING / BLOCKED
- deterministic value when available
- exact canonical input-state IDs
- blockers and warnings
- deterministic feature-value ID

A blocked feature is structurally prohibited from carrying a value.

## Feature bundles

`FeatureBundle` binds all computed features for one security and evaluation boundary to:

- feature-registry ID
- accepted canonical market-state IDs
- excluded market-state IDs
- overall PASS / WARNING / BLOCKED
- deterministic bundle ID

This bundle becomes the preferred quantitative input to future alpha engines and research agents.

## Initial daily market features

V1 includes deterministic daily-bar definitions for:

- 1-day return
- 5-day return
- 20-day return
- 10-day simple moving average
- 20-day simple moving average
- 50-day simple moving average
- 14-day ATR
- 20-day realized volatility
- 20-day average share volume
- 252-day high-position ratio

The 252-day high-position feature is optional in V1; insufficient history blocks that feature but does not by itself block a bundle when all core features are available.

## Canonical daily-bar handling

`DailyBarFeatureEngine` accepts only canonical market states for `OHLCV_1D` with `1D` bars. It:

- rejects future market states and future bars
- excludes blocked/no-canonical states while preserving their IDs in lineage
- rejects mixed-security inputs
- rejects conflicting canonical bars for the same bar end
- deterministically handles repeated identical canonical states
- computes each feature only from the exact lookback it requires

A warning-grade canonical bar propagates only to features whose lookback actually contains that bar.

## Initial formulas

Returns use close-to-close arithmetic return.

Simple moving averages use the arithmetic mean of closing prices.

ATR uses the standard true-range maximum of high-low, high-prior-close, and low-prior-close over the configured period.

Realized volatility uses population standard deviation of log returns annualized by the configured factor.

Average volume uses arithmetic mean daily share volume.

High-position is current close divided by the highest high in the configured window.

## Current scope

V1 is a deterministic reference implementation. It does not select data vendors, call live APIs, deploy AWS, alter SH24/SH25, modify TradingView, mutate PAPER execution, connect a broker, automate options, or enable live trading.

## Next stage

Stage 5 should define the Research Council agent contracts over immutable evidence and feature bundles. Agents should receive structured canonical facts/features plus lineage references, not raw provider responses, and they should have no direct execution authority.
