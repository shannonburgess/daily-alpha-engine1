# Daily Alpha Research Council V1

## Purpose

The Research Council is the first institutional reasoning layer above canonical evidence and deterministic features. It is intentionally a research layer, not a trading controller.

The council preserves disagreement among specialized analysts so a later CIO/Fusion layer can evaluate competing views rather than inheriting a pre-averaged consensus.

## First-pass analyst roles

- Momentum
- Rotation
- Catalyst
- Fundamental
- Macro
- Institutional
- Behavioral
- Bull
- Bear
- Skeptic
- Risk Analyst

Each role has a versioned mandate and a deterministic mandate ID.

## Authority boundary

Research analysts cannot:

- place orders
- authorize trading
- enable live trading
- mutate portfolio state
- change risk limits
- inspect peer opinions before submitting their first-pass view

The later CIO/Fusion layer may consume council opinions. The independent analysts may not consume each other's first-pass conclusions in V1.

## Point-in-time inputs

Every analyst receives an `AgentInputPacket` containing exact `CouncilInputRef` records. Each input reference includes:

- input kind
- immutable input ID
- availability timestamp
- quality label
- readiness status

Any input that became available after the analysis `as_of` timestamp is rejected before the analyst can see it.

Input kinds include canonical features, evidence, market state, event state, research facts, quant-model outputs, portfolio context and regime context.

## Structured opinion contract

An analyst opinion contains:

- role and mandate lineage
- exact input-packet lineage
- readiness status
- directional research stance
- normalized score from -100 to +100 when a view is possible
- conviction/confidence
- input-quality score
- thesis
- counterpoint
- cited supporting/opposing/uncertainty inputs
- invalidation conditions
- uncertainty codes
- blockers/warnings
- reasoning-engine identity/version

A blocked opinion cannot carry a directional score or stance.

Every non-blocked opinion must cite governed inputs and state at least one condition that would invalidate the thesis.

## Research Council packet

`ResearchCouncilAssembler` verifies:

1. security and timestamp context match;
2. packet mandate IDs match the registered mandate;
3. required input kinds are present;
4. no duplicate role is submitted;
5. every opinion maps to its own role's input packet;
6. every cited input actually existed in that packet;
7. all required council roles are present;
8. blocked/warning analyst states propagate visibly.

The resulting `ResearchCouncilPacket` deliberately has **no composite score, majority vote, BUY/SELL action or capital allocation**.

Those belong to later layers:

`Research Council -> CIO/Fusion -> Portfolio Construction -> Independent Risk Governor -> Execution`

## Adversarial design

Bull, Bear and Skeptic are intentionally separate mandates.

- Bull constructs the strongest evidence-backed positive-asymmetry case.
- Bear constructs the strongest evidence-backed case against committing or retaining risk.
- Skeptic searches for stale, missing, contradictory, crowded or weakly supported evidence.

Their disagreement is useful information and must not be suppressed.

## V1 status

This contract is research-only. It does not call an LLM, select an AI vendor, place a trade, connect a broker, deploy AWS resources or modify SH24/SH25. Future reasoning-engine adapters must implement these contracts rather than bypass them.
