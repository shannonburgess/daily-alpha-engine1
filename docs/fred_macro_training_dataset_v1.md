# FRED Macro Training Dataset Packet V1

## Purpose

This contract binds the deterministic FRED initial-release macro feature corpus to the existing immutable point-in-time training-dataset assembler.

It closes a lineage gap between two already merged research components:

1. `FredMacroFeatureCorpus`, which proves exactly which FRED initial-release observations were usable at each declared historical decision boundary; and
2. `build_point_in_time_training_dataset`, which combines point-in-time features with independently evidenced realized labels and excludes labels that were not mature by the dataset snapshot cutoff.

The packet does not create labels, download data, fit a model, select a model, promote a model, mutate PAPER state, authorize trading, or enable live execution.

## Required inputs

The builder accepts:

- one immutable `FredMacroFeatureCorpus`;
- one frozen `TrainingDatasetAssemblyPolicy`;
- independently valid `RealizedRLabelObservation` records; and
- an explicit timezone-aware dataset `as_of` boundary.

The policy feature schema must exactly match the feature names declared by the FRED corpus. V1 deliberately does not permit a caller to silently drop or inject macro features between corpus assembly and dataset assembly.

## Lineage

`FredMacroTrainingDatasetPacket` binds:

- the exact `corpus_id`;
- exact FRED feature-specification IDs;
- exact bounded FRED batch IDs;
- exact corpus source revisions;
- the existing dataset `assembly_id`; and
- therefore the exact included feature-observation IDs, included label IDs, excluded immature label IDs, and immutable `dataset_id` already carried by the assembly result.

Any included feature observation must belong to the bound FRED corpus. Label rows outside the declared security/decision matrix fail closed through the existing dataset assembler.

## Maturity and no-lookahead behavior

The FRED feature corpus already enforces `known_at <= decision_at` using provider-derived initial-release evidence. The dataset assembler independently enforces that labels mature only after the decision and are included only when `label_known_at <= dataset.as_of`.

An immature label is excluded rather than guessed. The packet still binds the full source corpus, making it explicit which feature evidence existed even when a corresponding realized outcome was not yet mature at the dataset snapshot boundary.

## Evidence boundary

This is research plumbing, not empirical alpha evidence.

A synthetic or fixture packet proves deterministic assembly behavior only. A real point-in-time model experiment still requires:

1. successful staging proof of the deployed FRED `output_type=4` capture contract;
2. immutable non-overlapping historical FRED evidence across the required horizon;
3. independently trustworthy point-in-time realized-label evidence;
4. dataset assembly at declared historical cutoffs;
5. strict TRAIN -> VALIDATION -> untouched TEST evaluation; and
6. comparison against frozen controls without using TEST data for fitting or selection.

No predictive-alpha claim is authorized merely because this packet can be assembled.

## Authority

The packet is permanently research-only:

- `labels_created=false`
- `retuning_authorized=false`
- `promotion_authorized=false`
- `paper_mutation_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`

The nested dataset and assembly objects retain their existing false execution-authority flags as well.
