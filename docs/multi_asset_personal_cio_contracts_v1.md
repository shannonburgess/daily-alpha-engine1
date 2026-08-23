# Multi-Asset Personal CIO Contracts V1

Status: **REPO-ONLY / RESEARCH-AND-PRODUCT ARCHITECTURE / NO EXECUTION AUTHORITY**

> **ConvexRidge Quant is an agentic multi-asset investment intelligence and portfolio operating system.**
>
> **Find the opportunity. Choose the best expression. Size the risk. Explain the decision. Preserve investor control.**

This slice implements the first asset-neutral contracts from issue #327 without changing the current SH24/SH25 equity validation program, PAPER execution policy, TradingView, AWS runtime, broker routing, or live-trading authority.

## Sequencing boundary

The current validation order remains:

1. SH24 CONTROL deterministic Pine/Python parity.
2. SH25 CHALLENGER deterministic Pine/Python parity.
3. Historical point-in-time TradingView parity evidence.
4. Genuine forward TradingView parity evidence.
5. Issue #213 PAPER-shadow reliability and realized evidence.

The contracts in this slice may be used for repo-only product architecture and tests. They may not promote unvalidated multi-asset recommendations into PAPER or live execution.

## Asset taxonomy

Primary asset classes are mutually distinct risk containers:

- `EQUITY`
- `FIXED_INCOME_CREDIT`
- `COMMODITY`
- `DIGITAL_ASSET`
- `FX_CASH_RESERVE`

Factor, sector/industry, thematic, and active-strategy labels are modeled separately as overlays. An equity ETF can therefore remain `EQUITY` while simultaneously carrying semiconductor, momentum, or AI-infrastructure overlays without double-counting those overlays as separate primary asset classes.

## Investment Opportunity Envelope

`InvestmentOpportunityEnvelope` is a versioned, point-in-time, deterministic opportunity contract. It carries thesis, asset class, exposure, instrument, structure, direction, risk, liquidity/capacity, volatility/sensitivity, portfolio fit, recommendation sizing, alternatives, account eligibility, evidence, lineage, agent-opinion references, blockers, and warnings.

The contract does not require equity-only fields. Tests instantiate fixed-income, commodity, and digital-asset opportunities without stock-specific metadata.

Every envelope has deterministic `opportunity_id` identity and hard false authority flags:

- `execution_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`

## Personal CIO Mandate

`PersonalCIOMandate` separates durable customer/account policy from ConvexRidge house guidance. It supports risk profile, target volatility, liquidity reserve, allowed/prohibited asset classes, instrument permissions, position limits, dimension limits, objectives, restrictions, and evidence.

The mandate is not an order ticket and does not grant execution authority.

## Governed Risk Override

`evaluate_risk_override` separates:

1. ConvexRidge recommended quantity/risk.
2. Customer-selected quantity/risk.
3. Objective hard constraints.

A risk-tolerance difference produces a warning and acknowledgment requirement, not an arbitrary hard block. The regression fixture covers the canonical example:

- recommended: 2 long-call contracts / $21,000 premium at risk;
- customer-selected: 50 contracts / $525,000 premium at risk;
- override multiple: 25x;
- house recommendation: `REDUCE`;
- no hard block when account/mandate/data/liquidity/safety constraints remain satisfied;
- acknowledgment required until the customer records it;
- execution authority remains false even after acknowledgment.

Hard blocks are reserved for objective failures: unreliable required data, insufficient buying power, unsupported/not-authorized account capability, mandate prohibition, liquidity/capacity, regulatory/compliance, broker/custodian rejection, or system safety.

## Broker / Custodian Capability Map

`BrokerCapability` is read-only. Each asset-class/instrument pair resolves explicitly to one of:

- `AVAILABLE`
- `NOT_AUTHORIZED`
- `NOT_SUPPORTED`
- `DATA_UNAVAILABLE`

Unknown combinations default to `NOT_SUPPORTED`; the platform never pretends an account can trade every asset.

## Portfolio Digital Twin

`PortfolioDigitalTwin` carries point-in-time NAV, cash, collateral, buying power, positions, economic exposure measures, volatility, drawdown, liquidity reserve requirement, and exact evidence lineage.

`DigitalTwinPair` enforces a current-to-pro-forma relationship:

- current twin must be `CURRENT`;
- pro-forma twin must be `PRO_FORMA`;
- both must share the same portfolio identity;
- pro-forma must reference the exact current `twin_id`;
- pro-forma may not predate the current snapshot.

No trade is executed by creating a pro-forma twin.

## Scenario Lab contract

`ScenarioRequest` requires the scenario `as_of` to equal the exact portfolio snapshot `as_of`; this prevents a later snapshot from being silently substituted into an earlier decision context. Each shock uses exactly one explicit unit: relative percentage, basis points, or absolute change.

`ScenarioResponse` is explicitly modeled and may not claim to be an observed market value.

## Cross-Asset Opportunity Translator

`rank_expression_candidates` is a deterministic first translation layer. It ranks supported/available expressions ahead of unavailable/unsupported ones, then by suitability score and stable tie-breakers. A designated cash/no-position expression must remain in the result.

This ranking is product/research intelligence only. It does not create an execution route.

## Agent track records and decision replay

`AgentTrackRecord` captures point-in-time sample size, directional hit rate where meaningful, expectancy/R, drawdown/R, loss streak, calibration error, stale-data incidence, version, domain, and evidence.

`DecisionReplayRecord` preserves the evidence and agent-opinion lineage available at the decision time plus CIO, portfolio, risk, opportunity, recommended-size, override, and broker-capability references. An eventual outcome may be linked only when its observation timestamp is at or after the original decision timestamp; future information cannot predate or replace the historical decision snapshot.

## Explicit non-goals

This V1 slice does **not**:

- change SH24 or SH25;
- mutate TradingView;
- change stock-primary PAPER execution;
- enable options, futures, digital-asset, FX, bond, or commodity execution;
- connect a broker, custodian, exchange, or paid provider;
- deploy AWS resources;
- merge the separate institutional command-center PR stack;
- authorize capital;
- enable live trading.

`trading_authorized=false` and `live_trading_enabled=false` remain invariants.
