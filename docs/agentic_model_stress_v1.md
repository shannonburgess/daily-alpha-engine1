# Daily Alpha — Model Stress & Regime Robustness V1

## Purpose

Stage 9H adds a model-risk layer above Stage 9G quantitative model governance. Stage 9G asks whether a model/version has acceptable point-in-time validation evidence. Stage 9H asks a different institutional question: **does the governed model remain sufficiently robust across adverse market regimes and explicit stress scenarios?**

A Stage 9H PASS or WARNING is research/model-risk evidence only. It does not authorize portfolio construction, capital, execution, broker routing, or live trading.

## Authority chain

The model-research path becomes:

`canonical evidence/features -> quant model view -> Stage 9G model governance -> Stage 9H stress/regime robustness -> CIO/Fusion research`

The higher authority hierarchy remains unchanged:

`Governance Lock > Independent Risk Governor > CIO/Fusion > Portfolio Construction / Research Council / Quant Models > Canonical Evidence`

Stage 9H can only remove a model view from the stress-qualified research set. It cannot upgrade a Stage 9G-blocked model, override deterministic risk, or create an order.

## Scenario registry

`StressScenarioDefinition` is immutable by `(scenario_id, scenario_version)`. Each definition has an explicit `effective_at` boundary and one institutional scenario class:

- `HISTORICAL_SHOCK`
- `TREND_DOWN`
- `RANGE`
- `HIGH_VOLATILITY`
- `LIQUIDITY_STRESS`
- `CORRELATION_SHOCK`
- `MACRO_SHOCK`

The registry rejects silent redefinition of a scenario version. A future-effective scenario cannot be used to support a historical assessment.

## Point-in-time stress result contract

`ModelStressResult` binds one model/version to one scenario/version and preserves:

- `known_at`
- stress window start/end
- sample size
- stressed expectancy/R
- stressed Sharpe
- stressed maximum drawdown
- worst loss/R
- recovery periods
- capacity retention
- stability score
- immutable input-lineage IDs

The window must end no later than `known_at`. A result whose `known_at` is later than the model-view `as_of` boundary is ignored for that historical assessment. This prevents later stress runs from repairing an earlier research decision.

## Default robustness policy

`ModelStressPolicy` requires a minimum scenario count plus explicit required regime classes. The default required set is historical shock, trend-down, high-volatility, liquidity-stress, and macro-shock. Thresholds cover:

- stressed expectancy/R floor
- stressed Sharpe floor
- maximum stressed drawdown
- worst loss/R floor
- maximum recovery periods
- minimum capacity retention
- minimum stability
- minimum passing-scenario ratio

Required classes must be represented by at least one passing scenario. A failed required class is a blocker even if aggregate pass ratio remains high. Optional scenario failures can remain warning-grade when required coverage and the aggregate pass ratio still satisfy policy.

## Upstream governance binding

Every Stage 9H assessment is bound to the exact Stage 9G `ModelGovernanceAssessment.assessment_id`. A model view that is not eligible under Stage 9G is always blocked by Stage 9H regardless of its stress metrics.

The Stage 9H packet also binds the exact Stage 9G packet ID, stress scenario registry ID, policy ID, model-view IDs, per-scenario assessment IDs, blockers, warnings, and the final stress-qualified model-view set.

## Determinism and replay

Inputs are deduplicated by immutable model-view/result identities and sorted before IDs are computed. Reordering scenario definitions, model views, or stress results cannot change the Stage 9H packet identity when the logical evidence set is unchanged.

This makes the stress gate suitable for later durable evidence storage, historical replay, model-risk review, and command-center visualization.

## Command-center interpretation

Recommended model-risk tiles are:

- Stage 9G validation status
- Stage 9H stress status
- scenario coverage count
- required regime coverage
- scenario pass ratio
- failed scenario IDs/reasons
- worst stressed drawdown
- worst loss/R
- longest recovery
- lowest capacity retention
- upstream governance assessment ID
- stress packet ID

The dashboard should distinguish `PASS`, `WARNING`, and `BLOCKED` without presenting any of them as execution authorization.

## Hard boundaries

This stage contains no AWS runtime/deployment code, no vendor activation, no live credentials, no paid-feed activation, no broker connection, no TradingView changes, no SH24/SH25 changes, no PAPER/live ledger mutation, no options automation, no capital authorization, no execution authorization, and no live trading.
