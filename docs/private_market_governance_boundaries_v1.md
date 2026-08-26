# ConvexRidge private-market governance boundaries V1

Private-market intelligence reuses the shared `InvestmentOpportunityEnvelope`, but reuse of thesis and
evidence does not imply reuse of investment authority.

For every future private-market decision context the platform carries independent identities for:

- investment vehicle,
- mandate,
- conflict policy,
- information-barrier policy,
- valuation policy,
- portfolio policy,
- risk policy,
- execution policy.

The V1 `InvestmentGovernanceBoundary` is research-only and rejects capital-commitment, execution,
trading, or live-trading authority. This lets Daily Alpha, future ConvexRidge Asset Management, and
future ConvexRidge Ventures share one opportunity vocabulary while preserving separate governed
authority paths.

## Private valuation is not a public market quote

`PrivateMarketValuationSnapshot` stores point-in-time valuation method, currency, evidence, and an
optional low/base/high range. A private valuation cannot be labeled as an observed market price.
That distinction prevents the Portfolio Digital Twin and Scenario Lab from treating a financing
round, manager mark, comparable-company analysis, or DCF estimate as if it were continuously
executable market data.

The decision context fails closed when valuation or governance evidence is future-dated or when the
valuation evidence is not included in the decision lineage.

## Instrument reuse

The shared opportunity contract already supports private-company equity, SAFE, convertible note,
private credit through `CREDIT`, and fund interests. A private-credit opportunity remains
`market_domain=PRIVATE` and `primary_asset_class=FIXED_INCOME_CREDIT`; it does not require a second
private-market asset taxonomy.

## Current boundary

These are repo-only contracts. They do not value a real company, authorize a capital commitment,
form or launch a venture fund, solicit investors, connect a broker/custodian, or create an execution
route. `trading_authorized=false` and `live_trading_enabled=false` remain invariant.
