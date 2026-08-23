# Daily Alpha model training and walk-forward evaluation V1

## Purpose

This layer defines how future adaptive/statistical/ML challengers may learn from Daily Alpha evidence without contaminating the frozen SH24 CONTROL or SH25 CHALLENGER strategy definitions.

SH24 and SH25 remain source-controlled deterministic strategies. This training layer is research-only and creates no PAPER, portfolio, broker, capital, execution, or live-trading authority.

## Current-main reconciliation

The research branch is intentionally validated against current authoritative `main` `1370d3c579bc41ae7a2320a3aae096358fb5c34f`, which includes the merged V1 prospect opportunity-board launch blocker from PR #338. That product-surface merge is independent of the model-training contracts and does not alter SH24/SH25 semantics, point-in-time dataset rules, model fitting, validation selection, test isolation, or any execution authority.

## Point-in-time rule

Every training example represents one historical decision boundary. Features must have been known no later than that boundary. The realized label must mature only after the decision and must be fully known by the dataset snapshot `as_of` cutoff.

A model must never receive revised or future information as though it had been available at the historical decision time. Feature values, labels, source revisions and evidence IDs are retained in deterministic dataset lineage.

## Point-in-time dataset assembly

V1 now includes a deterministic assembly boundary between raw historical observations and the immutable `TrainingDatasetSnapshot`.

Each `PointInTimeFeatureObservation` records:

- security and historical decision timestamp;
- exact feature name/value;
- when that feature value was known;
- evidence ID;
- source revision.

Each `RealizedRLabelObservation` records:

- security and historical decision timestamp;
- fixed label horizon;
- realized R;
- when the outcome became knowable;
- exact label evidence IDs;
- source revision.

`TrainingDatasetAssemblyPolicy` freezes the feature-schema version, label definition, required feature names and label horizon. `build_point_in_time_training_dataset` then fails closed on future-dated observations, feature-schema drift, conflicting feature values, conflicting labels, labels without a matching feature row, feature rows without labels, and label-horizon mismatch.

Labels that have not matured by the dataset `as_of` boundary are excluded explicitly and their label IDs remain recorded in assembly lineage. They are never converted to zero, guessed, or allowed to leak into the snapshot. At least one mature example is required.

The assembly result records the exact feature-observation IDs, label IDs, excluded immature-label IDs, policy identity, source revisions and final dataset identity. Input ordering and exact duplicate observations do not change the resulting identity.

## Dataset identity

A dataset snapshot is identified from:

- dataset `as_of` cutoff;
- feature-schema version;
- label definition;
- normalized training-example IDs;
- exact source revisions, including the assembly policy identity.

Example identity includes security, decision timestamp, feature-known-at timestamp, label-known-at timestamp, label horizon, normalized features, realized R and evidence lineage. Input order does not change dataset identity.

## Walk-forward protocol

Each fold contains strictly chronological, non-overlapping windows:

1. `TRAIN` — may be used for fitting and feature/model estimation;
2. `VALIDATION` — may be used for model/threshold/hyperparameter selection but is out of sample relative to fitting;
3. `TEST` — final untouched evaluation window.

The V1 contract hard-blocks any declaration that validation or test observations may be used for fitting. Test outcomes cannot influence fitting, feature selection, threshold selection or hyperparameter selection.

The first implemented fit path is a dependency-free deterministic ridge-linear `LINEAR_SCORE` baseline. Every candidate specification is declared before comparison, carries an explicit finite signal threshold, and is fit on the exact TRAIN IDs only. Feature means, scales, intercept and coefficients are derived exclusively from TRAIN.

`run_ridge_walk_forward_challenger` fits all predeclared candidates on TRAIN, evaluates candidate strategy results only on VALIDATION, selects the fixed winner from validation evidence, and evaluates that exact artifact on the untouched TEST partition. Regression tests prove that even extreme changes to TEST outcomes do not change fitted coefficients or the validation-selected specification.

Future stronger tree or ensemble challengers must obey the same partition, artifact-lineage and no-test-leakage contracts rather than introducing a parallel training path.

## Evaluation

The first out-of-sample record tracks:

- sample count;
- hit rate;
- expectancy/R;
- profit factor;
- cumulative R;
- maximum drawdown/R.

The fit layer also retains exact partition regression diagnostics such as MAE, RMSE and R-squared for model-analysis purposes. These are descriptive research evidence, not promotion authority.

A research candidate cannot self-promote based on these metrics. Separate model-governance, stress/robustness, paper-shadow and governance gates remain required before any future promotion decision.

## Relationship to SH24 / SH25

The intended hierarchy is:

`SH24 CONTROL` -> frozen deterministic baseline

`SH25 CHALLENGER` -> frozen deterministic challenger

`future adaptive/ML challengers` -> trained only on point-in-time research datasets and evaluated walk-forward

All books, source lineage, performance and promotion decisions remain separate. An adaptive model must beat or complement the controls on genuine out-of-sample evidence; it does not replace them because it fits historical data.

## Current evidence boundary

The repository now contains the point-in-time assembly contracts, deterministic dataset lineage, real ridge fitting, validation-only selection and untouched TEST evaluation code path. This does **not** mean a predictive model has been validated on market history.

A genuine historical model study still requires real point-in-time feature observations and matured outcome labels with trustworthy `known_at` and source-revision evidence. Existing fixture data proves protocol integrity only. Missing historical provenance must not be replaced by present-day reconstructed values that were not demonstrably known at the original decision boundary.

## Safety

This module is repo-only. It does not activate model providers, data vendors, AWS production services, TradingView changes, PAPER execution, broker routing or live trading. `promotion_authorized=false`, `paper_mutation_authorized=false`, `trading_authorized=false` and `live_trading_enabled=false` remain fail-closed research invariants.
