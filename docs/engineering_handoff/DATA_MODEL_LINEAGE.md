# Data and Model Lineage

Daily Alpha is designed so an engineer can reconstruct **what was known, when it was known, which exact source produced it, and which model/strategy consumed it**.

## Core timestamps

### `decision_at`

The historical decision boundary. A feature cannot be used if its trustworthy availability occurs after this timestamp.

### `known_at`

The earliest timestamp the system is willing to claim the information was available for model use. This is an evidence claim, not simply the date inside a provider payload.

### `captured_at`

The time Daily Alpha durably captured a provider response/receipt. For generic Massive/Tiingo/FRED staging captures, this is the only currently authorized known-at basis unless a separate provider-specific historical-availability contract proves otherwise.

## Historical backfill rule

A provider response captured today may contain observations from months or years ago. That **does not** mean Daily Alpha knew those observations at the historical date.

The merged historical-capture contract records:

- `capture_mode` (`CURRENT_WINDOW` or `HISTORICAL_BACKFILL`);
- requested start/end dates;
- `known_at_basis=CAPTURED_AT_ONLY`;
- `historical_known_at_backdating_authorized=false`.

The point-in-time feed adapter binds these fields into deterministic evidence identity and keeps model `known_at` at the trusted capture time. Historical request dates cannot be substituted for `known_at`.

## Evidence identity

Evidence-bearing records generally include or derive deterministic identifiers from:

- provider/source identity;
- security/target identity;
- timestamps;
- source revision/version;
- immutable raw-object key where applicable;
- raw SHA-256 and byte count;
- normalized record content.

If raw bytes do not match the receipt hash/size, the adapter fails closed.

## Feature observations

`PointInTimeFeatureObservation` is the model-facing feature contract. Its key concepts are:

- `security_id`;
- `decision_at`;
- `feature_name` and finite `feature_value`;
- trustworthy `known_at`;
- `evidence_id`;
- `source_revision`.

The invariant is:

```text
known_at <= decision_at
```

If this is false, the feature is future knowledge and must not enter that decision row.

## Label observations

Labels remain separate from feature evidence. `RealizedRLabelObservation` carries:

- security and decision identity;
- label horizon;
- realized R;
- `known_at` for label maturity;
- evidence IDs;
- source revision.

Required chronology:

```text
label_known_at > decision_at
```

A label that has not matured by the dataset snapshot cutoff is excluded rather than guessed or leaked.

## Dataset assembly

`build_point_in_time_training_dataset` requires a frozen feature schema and label definition/horizon. It rejects:

- future feature/label decision rows;
- missing or orphan labels;
- conflicting observations;
- feature-schema mismatch;
- label-horizon mismatch;
- rows with no mature label at the dataset cutoff.

Dataset identity includes normalized examples and source-revision lineage.

## Walk-forward isolation

Training is chronological and role-separated.

### TRAIN

Only TRAIN IDs may affect:

- feature normalization;
- coefficients/parameters;
- target construction;
- fitting.

### VALIDATION

Only VALIDATION evidence may choose among predeclared candidate specifications and explicit thresholds.

### TEST

TEST is untouched until the winning validation specification is already frozen. TEST labels/metrics must not alter parameters or selection.

Regression coverage intentionally changes TEST labels by extreme amounts and verifies that fitted parameters and validation-selected specifications do not change.

## Frozen-control comparison

After final TEST evaluation is complete, a research candidate may be compared with both frozen Pine controls:

- SH24 CONTROL;
- SH25 CHALLENGER.

The benchmark requires candidate/control evaluations to share the exact dataset, fold, ordered TEST cohort, and SHA-256-bound TEST evidence artifact. The comparison is evaluation-only and cannot retune the model.

## TradingView / Pine lineage

For genuine SH24/SH25 strategy evidence, preserve exact:

- TradingView/Pine source identity;
- strategy version;
- model/book identity;
- timeframe;
- `process_orders_on_close=true` requirement;
- signal/event identity;
- bar and receipt timestamps;
- paired market-evidence artifact.

Do not infer missing TradingView input values and do not mutate the script/configuration to force agreement.

## Evidence vs conclusion

These are different claims:

- “the fitter is leak-proof under regression tests” — code capability;
- “the staging feed captured immutable historical raw bytes” — acquisition evidence;
- “the feature was historically knowable at the decision boundary” — stronger availability evidence;
- “the model produced positive untouched OOS results” — empirical model evidence;
- “the model has predictive alpha” — a conclusion requiring sufficient robust evidence;
- “the model may trade live capital” — a separate authority decision.

Never jump from one level to the next without its evidence gate.