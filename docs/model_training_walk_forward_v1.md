# Daily Alpha model training and walk-forward evaluation V1

## Purpose

This layer defines how future adaptive/statistical/ML challengers may learn from Daily Alpha evidence without contaminating the frozen SH24 CONTROL or SH25 CHALLENGER strategy definitions.

SH24 and SH25 remain source-controlled deterministic strategies. This training layer is research-only and creates no PAPER, portfolio, broker, capital, execution, or live-trading authority.

## Current-main reconciliation

This research slice starts from authoritative `main` `39fae2d27df3d5b273aa1a5a3e7b0ea09499dd92`, which includes the merged SH24/SH25 parity harnesses, point-in-time training V1, walk-forward label-boundary purging, paired TradingView evidence capture, the complete V1 prospect opportunity-board contract, and the manual-only V1 staging proof workflow.

The logistic-baseline work is additive and research-only. It does not alter SH24/SH25 semantics, Pine inputs, TradingView, discovery qualification, PAPER execution, prospect output, AWS production state, or any execution authority.

## Point-in-time rule

Every training example represents one historical decision boundary. Features must have been known no later than that boundary. The realized label must mature only after the decision and must be fully known by the dataset snapshot `as_of` cutoff.

A model must never receive revised or future information as though it had been available at the historical decision time. Feature values, labels, source revisions and evidence IDs are retained in deterministic dataset lineage.

## Point-in-time dataset assembly

V1 includes a deterministic assembly boundary between raw historical observations and the immutable `TrainingDatasetSnapshot`.

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

The contract hard-blocks any declaration that validation or test observations may be used for fitting. Test outcomes cannot influence fitting, feature selection, threshold selection or hyperparameter selection.

Label maturity is also enforced at the fold boundary, not only at the dataset snapshot. A TRAIN example is purged if its label is not known strictly before VALIDATION starts. A VALIDATION example is purged if its label is not known strictly before TEST starts. Purged IDs remain deterministic fold lineage so boundary-crossing outcomes cannot disappear silently or contaminate the next stage.

## Interpretable baseline sequence

The first implemented fit path is a dependency-free deterministic ridge-linear `LINEAR_SCORE` baseline. Every candidate specification is declared before comparison, carries an explicit finite signal threshold, and is fit on the exact TRAIN IDs only. Feature means, scales, intercept and coefficients are derived exclusively from TRAIN.

`run_ridge_walk_forward_challenger` fits all predeclared candidates on TRAIN, evaluates candidate strategy results only on VALIDATION, selects the fixed winner from validation evidence, and evaluates that exact artifact on the untouched TEST partition. Regression tests prove that even extreme changes to TEST outcomes do not change fitted coefficients or the validation-selected specification.

The second interpretable baseline is a dependency-free deterministic L2 `LOGISTIC_CLASSIFIER`. Its binary training target is frozen as `REALIZED_R_GT_0`; target construction occurs only from exact TRAIN examples. Feature normalization is TRAIN-only, the intercept and coefficients are fit by deterministic fixed-iteration Newton updates, and both classes must be present in TRAIN or fitting fails closed.

Each logistic candidate predeclares its L2 penalty, fixed iteration count and explicit probability threshold before validation. `run_logistic_walk_forward_challenger` fits every candidate on exact TRAIN IDs, compares strategy outcomes on exact VALIDATION IDs, performs validation-only selection, and evaluates the fixed winner on untouched TEST. TEST outcomes cannot alter fitted parameters or validation-selected specification.

These simple interpretable baselines intentionally come before tree/ensemble challengers. A stronger `TREE_ENSEMBLE` or `GRADIENT_BOOSTED_TREES` path should be added only after genuine point-in-time evidence exists and only if it demonstrates measurable out-of-sample value beyond the simpler baselines and frozen SH24/SH25 controls. Any stronger model must reuse the same partition, label-maturity, artifact-lineage and no-test-leakage contracts rather than creating a parallel training path.

## Evaluation

The out-of-sample record tracks:

- sample count;
- hit rate;
- expectancy/R;
- profit factor;
- cumulative R;
- maximum drawdown/R.

The ridge fit layer also retains exact partition regression diagnostics such as MAE, RMSE and R-squared for model-analysis purposes. These are descriptive research evidence, not promotion authority.

A research candidate cannot self-promote based on these metrics. Separate model-governance, stress/robustness, paper-shadow and governance gates remain required before any future promotion decision.

## Relationship to SH24 / SH25

The intended hierarchy is:

`SH24 CONTROL` -> frozen deterministic baseline

`SH25 CHALLENGER` -> frozen deterministic challenger

`future adaptive/ML challengers` -> trained only on point-in-time research datasets and evaluated walk-forward

All books, source lineage, performance and promotion decisions remain separate. An adaptive model must beat or complement the controls on genuine out-of-sample evidence; it does not replace them because it fits historical data.

## Current evidence boundary

The repository contains the point-in-time assembly contracts, deterministic dataset lineage, walk-forward label purging, ridge fitting, logistic fitting, validation-only selection and untouched TEST evaluation code paths. This does **not** mean a predictive model has been validated on market history.

A genuine historical model study still requires real point-in-time feature observations and matured outcome labels with trustworthy `known_at` and source-revision evidence. Existing fixture data proves protocol integrity only. Missing historical provenance must not be replaced by present-day reconstructed values that were not demonstrably known at the original decision boundary.

No adaptive candidate should be compared against frozen SH24/SH25 as empirical evidence until that genuine point-in-time corpus exists. No trained artifact may self-promote into PAPER or live execution.

## Safety

This module is repo-only. It does not activate model providers, data vendors, AWS production services, TradingView changes, PAPER execution, broker routing or live trading. `promotion_authorized=false`, `paper_mutation_authorized=false`, `trading_authorized=false` and `live_trading_enabled=false` remain fail-closed research invariants.
