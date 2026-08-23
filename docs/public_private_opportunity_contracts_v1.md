# ConvexRidge public/private opportunity contracts V1

## Purpose

ConvexRidge needs one investment-intelligence language that can represent a listed equity,
Treasury, commodity, digital asset, private company financing, or venture-fund opportunity
without rebuilding the decision stack for each business line.

This V1 layer is intentionally below the Research Council, CIO/Fusion, Portfolio Construction,
Risk Governor, customer decision, and any future execution adapter.

It implements the product principle:

> Find the opportunity. Choose the best expression. Size the risk. Explain the decision.
> Preserve investor control.

## Public and private markets share the same thesis architecture

The core distinction is `market_domain`, not a completely separate model:

- `PUBLIC` covers listed/traded opportunities.
- `PRIVATE` covers private-company, private-credit, SAFE, convertible-note, fund-interest, and
  other private-market opportunities.

A private venture-backed company can therefore remain economically `EQUITY` while being
`market_domain=PRIVATE`. A public listed company expressing the same thesis can remain
`market_domain=PUBLIC`. This lets one thesis graph compare or connect both without pretending
that their liquidity, valuation, custody, or execution mechanics are identical.

## Investment vehicle separation

`InvestmentVehicleContext` carries opaque legal/business scope without granting authority.
It can identify, for example:

- the research platform,
- a future public-markets fund,
- a future ConvexRidge venture fund,
- a managed account,
- another future vehicle.

The context includes separate mandate, conflicts, and information-barrier policy identifiers.
It does **not** authorize capital allocation or execution. Those remain separate governed
layers so adding a new fund does not silently give a research object trading authority.

## Private-market terms

`PrivateMarketTerms` captures optional point-in-time financing context such as:

- company stage,
- financing instrument,
- post-money valuation,
- round size,
- ownership target,
- expected liquidity horizon,
- exact evidence IDs.

These fields are optional and never required for public securities.

## Conflicts and information barriers

Private investing creates conflicts that a public-market intelligence platform must preserve.
The V1 contract therefore carries explicit `ConflictDisclosure` objects for relationships such
as venture holdings, board roles, advisory relationships, public-market holdings, and commercial
relationships.

Information is classified as:

- `PUBLIC`,
- `CONFIDENTIAL`, or
- `MNPI_RESTRICTED`.

A deterministic invariant forbids `MNPI_RESTRICTED` information from being marked as permitted
for public-market research. This is an architectural information barrier, not a claim that the
system is legally or regulatorily complete.

## Public/private opportunity graph

`PublicPrivateOpportunityGraph` links multiple expressions of one investment thesis. Example:

`AI infrastructure thesis`

- public semiconductor equity,
- public electrical-equipment company,
- copper exposure,
- private grid-infrastructure company,
- private cooling company,
- cash/no-position alternative downstream.

Graph relationships include primary expression, alternative expression, supplier, customer,
bottleneck solver, hedge, and other.

This creates the foundation for a future Public/Private Opportunity Graph without building a
second recommendation system for ConvexRidge Ventures.

## Authority boundary

Every `InvestmentOpportunityEnvelope` and `PublicPrivateOpportunityGraph` is research-only in V1.
The contracts reject any attempt to set:

- capital-allocation authority,
- execution authority,
- trading authority, or
- live-trading enablement.

That keeps the current Daily Alpha validation path unchanged while allowing the architecture to
support future multi-asset, public-fund, and venture-fund businesses.

## Current implementation status

This V1 is a repo-only contract layer. It does not create or operate a legal entity, venture fund,
broker connection, custodian connection, private-company data feed, portfolio allocation,
production AWS resource, execution route, or live capital authority.
