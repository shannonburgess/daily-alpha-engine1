# Daily Alpha model training and walk-forward evaluation V1

## Purpose

This layer defines how future adaptive/statistical/ML challengers may learn from Daily Alpha evidence without contaminating the frozen SH24 CONTROL or SH25 CHALLENGER strategy definitions.

SH24 and SH25 remain source-controlled deterministic strategies. This training layer is research-only and creates no PAPER, portfolio, broker, capital, execution, or live-trading authority.

## Point-in-time rule

Every training example represents one historical decision boundary. Features must have been known no later than that boundary. The realized label must mature only after the decision and must be fully known by the dataset snapshot `as_of` cutoff.

A model must never receive revised or future information as though it had been available at the historical decision time. Feature values, labels, source revisions and evidence IDs are retained in deterministic dataset lineage.

## Dataset identity

A dataset snapshot is identified from:

- dataset `as_of` cutoff;
- feature-schema version;
- label definition;
- normalized training-example IDs;
- exact source revisions.

Example identity includes security, decision timestamp, feature-known-at timestamp, label-known-at timestamp, label horizon, normalized features, realized R and evidence lineage. Input order does not change dataset identity.

## Walk-forward protocol

Each fold contains strictly chronological, non-overlapping windows:

1. `TRAIN` — may be used for fitting and feature/model estimation;
2. `VALIDATION` — may be used for model/threshold/hyperparameter selection but is out of sample relative to fitting;
3. `TEST` — final untouched evaluation window.

The V1 contract hard-blocks any declaration that validation or test observations may be used for fitting. Test outcomes should not influence fitting, feature selection, threshold selection or hyperparameter selection.

A later orchestration layer may define rolling or expanding windows, but it must preserve the same chronology and dataset lineage.

## Evaluation

The first out-of-sample record tracks:

- sample count;
- hit rate;
- expectancy/R;
- profit factor;
- cumulative R;
- maximum drawdown/R.

These are descriptive evidence. A research candidate cannot self-promote based on these metrics. Separate model-governance, stress/robustness, paper-shadow and human/governance gates remain required before any future promotion decision.

## Relationship to SH24 / SH25

The intended hierarchy is:

`SH24 CONTROL` -> frozen deterministic baseline

`SH25 CHALLENGER` -> frozen deterministic challenger

`future adaptive/ML challengers` -> trained only on point-in-time research datasets and evaluated walk-forward

All books, source lineage, performance and promotion decisions remain separate. An adaptive model must beat or complement the controls on genuine out-of-sample evidence; it does not replace them because it fits historical data.

## Safety

This module is repo-only. It does not activate model providers, data vendors, AWS production services, TradingView changes, PAPER execution, broker routing or live trading. `promotion_authorized=false`, `paper_mutation_authorized=false`, `trading_authorized=false` and `live_trading_enabled=false` remain fail-closed research invariants.
