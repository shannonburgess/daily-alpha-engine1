# Daily Alpha CIO / Fusion V1

## Purpose

The CIO/Fusion layer converts independent Research Council opinions, quant-model views, and governed portfolio/regime context into a **security-level investment intent**.

It is the highest layer of investment judgment, but it is deliberately **not** the highest authority in the platform.

## Authority hierarchy

```text
Governance Lock
      ↓
Independent Deterministic Risk Governor
      ↓
CIO / Fusion
      ↓
Research Council + Quant Models
      ↓
Canonical Evidence / Features
```

The CIO may disagree with or override an individual analyst or quant model.

The CIO may **not**:

- override the Risk Governor;
- override the Governance Lock;
- authorize live trading;
- place an order;
- set an order quantity or limit price;
- mutate portfolio state directly;
- perform portfolio construction by itself.

## Inputs

`CIOFusionInput` binds the decision to:

- one exact `ResearchCouncilPacket`;
- zero or more point-in-time `QuantModelView` records;
- zero or more governed portfolio, regime, market, feature, event, or research context references.

Future model views or context are rejected.

Quant models such as SH24/SH25 can therefore remain governed expert inputs without becoming master keys.

## Investment actions

The CIO can express one of these investment intents:

- BUY
- WAIT
- HOLD
- ADD
- TRIM
- SELL
- HEDGE
- NO_ACTION

These are **research/portfolio intents**, not executable broker instructions.

A blocked Research Council cannot produce an active CIO investment action. In that condition the CIO is limited to WAIT or NO_ACTION. Independent deterministic risk controls may still reduce risk through their own authority path later.

## Explicit overrides

If the CIO disagrees with an analyst or quant model, the disagreement is recorded as an `OverrideRecord` containing:

- source type;
- exact opinion/model-view ID;
- source label;
- explicit rationale.

An override may reference only an input actually present in the fusion packet.

This allows Daily Alpha to answer questions such as:

- Did the CIO outperform SH24 by overriding it?
- Did ignoring the Bear analyst add or destroy value?
- Which agent/model overrides improved expectancy?
- Does a model still add incremental alpha after the CIO layer?

## Decision contract

`CIOInvestmentDecision` records:

- action;
- conviction;
- expected-alpha score;
- rationale;
- opposing case;
- invalidation conditions;
- cited analyst opinions;
- cited quant-model views;
- explicit overrides;
- blockers/warnings;
- reasoning-engine identity/version;
- immutable decision ID.

The decision contract hard-codes all execution, risk-override, governance-override, and live-trading authorities to false.

## Validation

`CIOFusionValidator` verifies:

1. security and point-in-time context;
2. council packet lineage;
3. analyst citation validity;
4. quant-model citation validity;
5. override-source validity;
6. blocked/warning input propagation;
7. blocked-council action restrictions;
8. no implicit risk or governance override.

## Separation from portfolio construction

The CIO decides **what the investment case implies**.

The next institutional layer decides **how much capital, if any, should be allocated relative to every other opportunity and the existing portfolio**.

That next layer should optimize marginal portfolio utility rather than convert CIO conviction directly into position size.
