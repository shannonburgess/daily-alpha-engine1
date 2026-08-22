# Daily Alpha quantitative model governance V1

## Purpose

Stage 9G adds an institutional model-risk boundary between quantitative model outputs and the CIO/Fusion research layer. A `QuantModelView` can no longer be treated as CIO-ready merely because it has a score and confidence. Its exact model/version must be registered, lifecycle-eligible, supported by validation evidence that was available at the model-view's point-in-time boundary, and inside explicit validation thresholds.

This is research governance only. A model marked SHADOW or VALIDATED is not authorized to construct a portfolio, send an order, receive capital, or trade live.

## Control chain

```text
canonical / feature / research lineage
              |
              v
        QuantModelView
              |
              v
   Stage 9G ModelRegistry
      + validation history
      + governance policy
              |
              v
 ModelGovernanceAssessment
              |
              v
   ModelGovernancePacket
              |
              +--> eligible model views may enter CIO/Fusion research
              +--> blocked/ungoverned views fail the eligibility assertion
```

## Immutable model/version registry

`ModelDefinition` identifies one exact model/version and records:

- model ID and model version;
- owner;
- lifecycle stage;
- effective timestamp;
- optional retirement boundary for a retired definition;
- human description;
- permanent research-only authority flags.

`ModelRegistry` rejects a second, different definition for the same `(model_id, model_version)` key. Changes that alter model behavior or governance identity therefore require an explicit new version/definition rather than silently rewriting history.

## Lifecycle stages

V1 defines four model-risk stages:

- `RESEARCH` — experimental; blocked from CIO model-view eligibility by the default policy;
- `SHADOW` — eligible only when validation thresholds pass;
- `VALIDATED` — eligible only when validation thresholds pass unless an explicit policy intentionally downgrades threshold failures to warnings;
- `RETIRED` — blocked.

These stages are not a capital ladder and do not imply execution permission.

## Validation evidence

`ModelValidationRecord` captures immutable point-in-time evidence for one model/version:

- validation as-of timestamp;
- validation window start/end;
- sample size;
- expectancy in R;
- Sharpe;
- Sortino;
- maximum drawdown;
- profit factor;
- stability score;
- validation method;
- immutable input-lineage IDs.

The validation window must end on or before the validation record's own as-of timestamp. Non-finite metrics are rejected. Drawdown and stability use bounded 0–1 contracts.

## No-lookahead rule

For a model view at time `T`, Stage 9G considers only validation records with `validation.as_of <= T`. A validation completed tomorrow cannot retroactively make today's model view eligible. The latest qualifying validation record is selected deterministically by `(as_of, validation_id)`.

This is critical for historical replay, backtest audit, and later model-attribution analysis.

## Governance policy

`ModelGovernancePolicy` is itself fingerprinted and supports explicit thresholds for:

- minimum sample size;
- minimum expectancy/R;
- minimum Sharpe;
- minimum Sortino;
- maximum drawdown;
- minimum profit factor;
- minimum stability score;
- eligible lifecycle stages.

A view is also blocked when its own `ReadinessStatus` is BLOCKED or when it lacks input lineage. A WARNING model view remains eligible but carries a governance warning.

## Governance assessment

Every model view produces a deterministic `ModelGovernanceAssessment` binding:

- model-view ID;
- model ID/version;
- model-definition ID;
- lifecycle stage;
- selected validation ID;
- PASS / WARNING / BLOCKED status;
- exact blockers/warnings;
- `eligible_for_cio_research`.

A blocked assessment can never claim CIO research eligibility.

## Multi-model packet and CIO boundary

`ModelGovernancePacket` binds all model assessments for one security and one research as-of boundary to:

- the exact `ModelRegistry.registry_id`;
- the exact `ModelGovernancePolicy.policy_id`;
- sorted assessment IDs;
- the exact set of eligible model-view IDs;
- packet-level blockers/warnings;
- a deterministic packet ID.

Input ordering and duplicate model views do not change the packet identity. `assert_views_eligible()` provides the explicit handoff boundary: a caller cannot pass an ungoverned, blocked, wrong-security, or future model view through that packet silently.

## Relationship to model attribution

Stage 9G creates the version/validation lineage needed for later attribution. A future attribution stage can compare realized outcomes by `model_id`, `model_version`, validation regime, feature lineage, and CIO override without losing which validation policy was in force when the model view was produced.

## Hard authority boundary

Stage 9G cannot authorize execution:

- `research_only = true`;
- `portfolio_construction_authorized = false`;
- `execution_authorized = false`;
- `trading_authorized = false`;
- `live_trading_enabled = false`;
- no broker connection;
- no AWS deployment;
- no vendor/credential activation;
- no TradingView mutation;
- no SH24/SH25 mutation;
- no PAPER/live execution mutation.

A model passing governance is eligible for governed research synthesis only.
