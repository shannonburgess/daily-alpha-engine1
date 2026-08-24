# FRED Initial-Release Macro Feature Corpus V1

## Purpose

This contract converts validated FRED `output_type=4` initial-release evidence into a deterministic matrix of point-in-time macro features for declared historical decision boundaries.

It is an evidence-assembly layer only. It does not download provider data, create labels, fit a model, select a model, promote a model, mutate PAPER state, authorize trading, or enable live execution.

## Inputs

The builder accepts:

- one or more already-validated `FredInitialReleaseBatch` objects;
- a frozen mapping from FRED series IDs to model feature names;
- declared security IDs that will share the macro state;
- explicit timezone-aware historical decision timestamps.

Every batch must already satisfy `FRED_OUTPUT_TYPE_4_INITIAL_RELEASE_V1`, including exact immutable raw-feed evidence and the conservative `NEXT_UTC_DAY_AFTER_REALTIME_START` availability rule.

## Multiple bounded captures

The staging ingestion path deliberately limits each historical capture to 31 calendar days. A real training corpus therefore needs many bounded captures over time.

V1 supports multiple captures per FRED series only when their observation dates do not overlap. This is intentionally strict. The same provider row captured more than once would be tied to different immutable raw evidence identities; silently choosing one copy would make lineage ambiguous. Operators should request adjacent, non-overlapping windows when building a long-run corpus.

## Point-in-time selection

For every security, decision timestamp, and declared feature, the builder chooses the latest initial-release observation satisfying both:

- `observation_date <= decision_at.date()`; and
- provider-derived `known_at <= decision_at`.

If no value was provably known at a required decision boundary, corpus assembly fails closed instead of forward-filling from future knowledge or inventing a value.

## Determinism and lineage

The resulting `FredMacroFeatureCorpus` binds:

- the exact feature specification IDs;
- normalized security IDs;
- exact decision timestamps;
- exact FRED batch IDs;
- exact point-in-time feature observation IDs;
- exact source revisions inherited from the selected initial-release rows.

Input ordering does not change the corpus identity.

## Evidence boundary

This code is **CODED** only until CI proves the branch and the change is merged.

Even after merge, it does not imply that real FRED history has been captured. Real empirical use still requires a successful staging proof from `.github/workflows/prove-fred-initial-release-staging.yml`, followed by immutable evidence accumulation across the desired non-overlapping windows.

Only then can these feature observations be combined with independently valid realized labels and passed into the existing strict `TRAIN -> VALIDATION -> untouched TEST` model-training pipeline.

No predictive-alpha claim is authorized by this contract.

## Authority

The corpus is permanently research-only:

- `labels_created=false`
- `retuning_authorized=false`
- `promotion_authorized=false`
- `paper_mutation_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`
