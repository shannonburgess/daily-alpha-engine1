# ConvexRidge Ventures architecture V1

## Product intent

ConvexRidge Ventures is a future private-markets/venture investment business that can consume
the same governed intelligence architecture as Daily Alpha and future public-market investment
vehicles without becoming part of the Daily Alpha execution path.

The platform should be able to ask two related but different questions from one structural thesis:

1. Which public assets express or benefit from the thesis?
2. Which private companies are creating, solving, or monetizing the same bottleneck?

## Shared intelligence, separate authority

The shared chain remains:

`Evidence -> Specialist Agents -> Research Council -> CIO/Fusion -> Portfolio -> Risk -> Decision`

The venture business may reuse evidence, thesis IDs, agent outputs, opportunity envelopes, and
portfolio/risk interfaces. It must keep separate vehicle, mandate, conflicts, information-barrier,
valuation, capital-allocation, and execution authority.

No venture-fund interest may silently alter a public-market recommendation. Any economic interest,
board role, advisory relationship, or commercial relationship must be represented as an explicit
conflict disclosure and preserved downstream.

## Public/private opportunity graph

A single economic thesis can contain both public and private nodes. Example:

`AI infrastructure`

- listed semiconductor producer,
- listed electrical-equipment supplier,
- copper exposure,
- private grid-software company,
- private cooling company,
- private power-management company.

The graph is research context. It does not imply that all nodes have comparable liquidity,
valuation certainty, time horizon, custody, eligibility, or executable pricing.

## Private-market specialist agents

Future private-market domains can plug into the same independent-agent contract. Candidate roles
include:

- Private Company / Venture Intelligence,
- Private Market Valuation,
- Founder / Team Evidence,
- Product / Adoption Evidence,
- Competitive Landscape,
- Financing / Cap Table,
- Private Liquidity / Exit Path,
- Conflict & Information Barrier,
- Venture Portfolio Construction,
- Venture Risk / Concentration.

These should remain specialist opinions. They do not directly authorize investment.

## Why this is being modeled now

The goal is to avoid a later fork where public markets use one identity/evidence/thesis model and
ConvexRidge Ventures requires a second one. The public/private opportunity contracts therefore
model `market_domain`, investment-vehicle context, private financing terms, conflicts, information
classification, and public/private thesis graph edges from the beginning.

## Current boundary

This document and its companion contracts are repo-only architecture. They do not form a legal
venture entity, launch a fund, solicit investors, value a real private company, create a capital
commitment, activate a private-market data source, or authorize any transaction.
