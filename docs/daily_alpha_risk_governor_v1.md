# Daily Alpha Independent Risk Governor V1

## Purpose

The Risk Governor is the independent deterministic capital-protection authority above CIO/Fusion and Portfolio Construction. It evaluates a proposed portfolio allocation against hard point-in-time limits and governance state. AI reasoning cannot override its decision.

## Authority hierarchy

`Governance Lock > Deterministic Risk Governor > CIO/Fusion > Portfolio Construction / Research Council / Quant Models > Canonical Evidence and Features`

The Risk Governor may approve or reject a portfolio proposal. Approval means only that the proposal passed the governed risk checks represented by this policy/version. It does **not** authorize capital, place an order, enable execution, or enable live trading.

## Inputs

The V1 governor consumes:

- exact `PortfolioAllocationProposal`
- exact `PortfolioSnapshot`
- point-in-time `RiskContext`
- point-in-time `GovernanceLockState`
- versioned `RiskPolicy`

All IDs and evaluation timestamps are deterministic and attributable.

## Hard controls

V1 evaluates:

- maximum security weight
- maximum sector weight
- maximum correlation-cluster weight
- minimum cash reserve
- maximum gross exposure
- maximum net exposure
- maximum portfolio volatility
- maximum turnover
- portfolio drawdown throttle
- liquidity / days-to-exit capacity
- material-event blackout proximity
- source/context freshness
- blocked upstream portfolio proposals
- governance emergency stop
- model-stack approval

Missing critical sector, correlation-cluster, liquidity, or material-event context for a risk increase fails closed.

## De-risking principle

A hard risk limit must not trap capital in a dangerous position. If an existing portfolio is already outside a limit, a proposal that genuinely reduces the violation is allowed to proceed through the Risk Governor with an explicit warning rather than being rejected solely because the post-change portfolio is still above the limit.

Examples:

- an overweight position may be reduced from 35% to 25% even if the current maximum is 10%
- an illiquid position may be reduced even when its days-to-exit exceeds the normal limit
- a portfolio above the volatility threshold may continue reducing exposure if estimated volatility improves
- excessive turnover caused solely by urgent de-risking is warning-grade rather than automatically blocking the reduction

New/increased risk does not receive this treatment.

## Governance Lock

`GovernanceLockState` sits above the Risk Governor. An emergency stop or unapproved model stack rejects the proposal regardless of CIO conviction or portfolio-construction utility.

The V1 state remains research-only: `execution_globally_enabled=false` and `live_trading_enabled=false`.

## Outputs

`RiskGovernorDecision` contains:

- APPROVED / REJECTED verdict
- `risk_governor_approved`
- exact proposal, portfolio, risk-context, policy, and governance lineage
- reviewed target allocations
- deterministic blocker and warning reason codes
- deterministic decision ID

It explicitly keeps `capital_allocation_authorized=false`, `execution_authorized=false`, `trading_authorized=false`, and `live_trading_enabled=false`.

## AWS target

When approved for AWS deployment, the intended path is:

`Portfolio Construction proposal -> Step Functions risk-evaluation state -> deterministic Risk Governor Lambda/container -> immutable risk decision in S3 + current decision state -> Execution Controller`

The execution controller must verify the exact approved risk-decision ID, current governance state, current account state, and current market state before any future PAPER or live route can proceed.

CloudWatch records health/latency, CloudTrail records infrastructure/API activity, KMS encrypts risk records, and IAM separates research, risk, and execution permissions.

This V1 implementation performs no AWS deployment, no broker call, no order placement, and no live authorization.
