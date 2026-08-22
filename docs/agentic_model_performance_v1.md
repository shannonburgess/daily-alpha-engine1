# Daily Alpha — Model Performance Attribution & Alpha-Decay Surveillance V1

## Purpose

Stage 9I adds rolling realized-outcome surveillance above Stage 9G model governance and Stage 9H stress robustness. Validation and stress testing establish whether a model was historically acceptable under controlled evidence. Stage 9I asks whether the model is **still behaving acceptably in realized research outcomes known as of the current boundary**.

This layer is research/model-risk surveillance only. It consumes immutable outcome records and cannot write to the PAPER ledger, change execution semantics, allocate capital, route to a broker, or enable live trading.

## Research path

`canonical evidence/features -> QuantModelView -> Stage 9G validation governance -> Stage 9H stress robustness -> Stage 9I realized performance surveillance -> CIO/Fusion research`

Each successive stage can restrict eligibility but cannot upgrade an upstream blocker.

## Immutable outcome attribution

`ModelOutcomeRecord` binds each realized outcome to:

- exact historical `model_view_id`
- model ID/version
- security ID
- measurement start/end
- `known_at` timestamp
- realized return and realized R
- observed fees in basis points
- immutable source/scorecard lineage IDs

The measurement window must end no later than `known_at`. Future-known outcomes are excluded from historical surveillance, preventing lookahead.

Outcome records are read-only research evidence. The contract hard-codes PAPER-ledger mutation, portfolio construction, execution, trading authorization, and live enablement to false.

## Rolling surveillance metrics

For each current model/version, Stage 9I aggregates deduplicated outcomes known by the packet `as_of` boundary and inside the versioned lookback window. The surveillance population is model/version-level and may span securities; each contributing result still preserves its exact security and historical model-view attribution. Metrics include:

- sample size
- wins / losses / breakeven outcomes
- hit rate
- expectancy/R
- profit factor
- cumulative R
- maximum drawdown measured on the cumulative-R path
- maximum consecutive loss streak
- exact Stage 9G baseline validation expectancy
- realized expectancy-decay fraction versus that baseline where the baseline is positive

A no-loss window represents profit factor as `None` rather than infinity so all persisted values remain canonical JSON.

## Insufficient history

A model with too few realized outcomes receives `WARNING`, not fabricated confidence and not an automatic performance failure. It remains research-eligible only if Stage 9G and Stage 9H are also eligible. Once the minimum sample threshold is reached, realized thresholds become enforceable blockers.

## Default performance policy

The versioned `ModelPerformancePolicy` controls:

- rolling lookback days
- minimum outcomes
- minimum hit rate
- minimum expectancy/R
- minimum profit factor
- maximum drawdown/R
- maximum consecutive loss streak
- maximum expectancy-decay fraction versus the exact Stage 9G validation baseline

Material deterioration produces `BLOCKED` and removes the model view from the performance-eligible CIO research set.

## Lineage guarantees

Stage 9I binds the exact:

- Stage 9G governance packet ID and assessment ID
- Stage 9H stress packet ID and assessment ID
- Stage 9G baseline validation ID
- model-view ID
- rolling outcome IDs
- performance policy ID
- metrics ID
- blockers / warnings
- final performance-eligible model-view set

Input reordering and duplicate outcome delivery cannot change the logical packet identity.

## Command-center interpretation

Recommended model-risk tiles include:

- Stage 9G validation status
- Stage 9H stress status
- Stage 9I realized-performance status
- rolling sample size
- rolling expectancy/R
- hit rate
- profit factor
- max drawdown/R
- max loss streak
- baseline expectancy/R
- expectancy decay percentage
- upstream packet/assessment lineage IDs

`PASS`, `WARNING`, and `BLOCKED` remain research/model-risk states, never execution authorization.

## Hard boundaries

No PAPER ledger mutation, no execution change, no AWS deployment, no live vendor call, no credential or paid-service activation, no broker connection, no TradingView mutation, no SH24/SH25 mutation, no portfolio-construction authorization, no capital/execution authorization, and no live trading.
