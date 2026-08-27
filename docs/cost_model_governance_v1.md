# ConvexRidge Cost & Model Governance V1

## Operating principle

ConvexRidge spends compute in proportion to the complexity and economic importance of the decision.

The routing rule is deliberately asymmetric:

1. satisfy required quality, latency, reliability, capability, security, and information-handling constraints;
2. only then minimize cost among the eligible compute paths;
3. if no candidate qualifies, escalate explicitly rather than silently lowering the quality floor.

This creates the architectural policy:

> Cheap where computation is commoditized. Expensive where judgment matters. Deterministic where truth must be exact.

## Compute ladder

The default compute path is:

1. **Deterministic code first** for exact calculations, accounting, portfolio math, Greeks, risk limits, liquidity checks, buying power, mandate rules, compliance checks, lineage, and execution validation.
2. **Low-cost model** for extraction, classification, tagging, routine summarization, and high-volume low-ambiguity tasks.
3. **Stronger reasoning model** for ambiguous research, conflicting evidence, structural thesis work, and higher-value synthesis.
4. **Premium or multi-model reasoning** only when required by quality thresholds, low confidence, high decision criticality, or material economic consequences.

The Cost & Model Governor does not infer that expensive equals better. Model quality must be measured and versioned by task family.

## LLM Gateway / Model Router relationship

Agents should not directly bind themselves to one model provider. The intended flow is:

`Agent -> ConvexRidge LLM Gateway -> Cost & Model Governor -> Model Router -> Eligible provider/model`

The gateway owns provider independence, prompt/version lineage, structured-output contracts, data-classification policy, rate limits, cost controls, evaluation scores, and fallback/escalation behavior.

Model providers remain replaceable components. ConvexRidge owns the intelligence architecture.

## Hard quality rule

Cost may never waive a required threshold. A candidate is ineligible if it fails any applicable constraint, including:

- required capability;
- minimum task quality score;
- maximum latency ceiling;
- minimum reliability score;
- required information classification support;
- deterministic-compute requirement;
- disabled/provider-policy state.

Only eligible candidates participate in cost minimization.

If no candidate qualifies, the route is `ESCALATION_REQUIRED`.

## Reuse and cache identity

ConvexRidge should not pay repeatedly for an intelligence result when the governed inputs are unchanged.

A reusable intelligence identity is derived from:

- evidence IDs;
- model ID and version;
- prompt ID and version;
- policy ID and version;
- point-in-time `as_of` boundary;
- task identity.

If that identity has already been computed and remains valid under retention/freshness rules, downstream products should reuse the structured result and lineage rather than recompute it.

This is particularly important for high-fan-out opinions such as Macro, SEC, Sector, Thematic, and Research Council state. Thousands of customer explanations should not cause thousands of identical upstream model calls.

## Context compression hierarchy

Large raw documents should be processed once into reusable structured evidence whenever possible:

`raw evidence -> extracted facts -> structured evidence -> specialist-agent opinion -> Research Council -> CIO/Fusion`

Higher layers consume only the evidence required for the decision while retaining exact source lineage for drill-down and audit.

## Infrastructure cost discipline

Microservices do not imply continuously running servers. The default early architecture should remain event-driven and server-native:

`EventBridge -> SQS -> Lambda / bounded compute -> S3 / DynamoDB`

Idle agents should approach zero compute cost. A workload should move to continuously running containers only after measured throughput/latency economics justify it.

### Storage lifecycle

Use a hot/warm/cold policy:

- **Hot:** current portfolio state, active evidence, fresh agent opinions, current risk and capability state.
- **Warm:** recent historical evidence and decision lineage used for replay, evaluation, and customer drill-down.
- **Cold:** older raw evidence and long-horizon archives that must remain auditable but do not require low-latency access.

Storage transitions must preserve immutable identity and lineage references.

## Real-time vs batch

Real-time/fast paths should be reserved for workloads where latency changes decision value, including:

- current portfolio/risk state;
- Risk Governor;
- broker/custodian capability;
- execution validation;
- material alerts and customer decision flows.

Scheduled or batched workloads should include where appropriate:

- SEC corpus processing;
- historical factor recomputation;
- attribution and scorecards;
- venture/private-market landscape scans;
- model evaluation suites;
- overnight research;
- bulk news classification and clustering.

## FinOps measurement

Cost efficiency must be observable at the same granularity as model quality. V1 tracks the following schema:

- `cost_per_agent_run_usd`
- `cost_per_recommendation_usd`
- `cost_per_customer_usd`
- `llm_cost_per_revenue_dollar`
- `data_cost_per_active_user_usd`
- `aws_cost_per_1000_opportunities_usd`
- `premium_model_escalation_rate`
- `cache_hit_rate`
- `cost_by_agent_usd`
- `quality_score_by_model`

These metrics should eventually be joined to task quality, latency, reliability, customer value, and economic impact so the platform can distinguish productive premium compute from waste.

## Safety and authority

This V1 is architecture and deterministic routing logic only. It does not activate a paid model provider, create credentials, deploy production AWS resources, authorize capital, alter TradingView, or enable execution/live trading.

The Cost & Model Governor has no investment authority. It selects an eligible compute implementation for an intelligence task. Research Council, CIO/Fusion, Portfolio Construction, Risk Governor, Customer Decision, and execution authority remain separately governed.

Tracks issue #330 and complements issue #327.