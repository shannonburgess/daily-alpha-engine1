# Daily Alpha Behavioral Intelligence V1

## Purpose

Daily Alpha treats sentiment and attention as behavioral evidence, not authoritative market truth. The behavioral layer normalizes point-in-time observations from independent news, social, forum, search, web, alternative-data, and vendor-composite sources before the Behavioral Analyst can use them.

## Intended provider adapters

The contracts are provider agnostic. Future adapters can represent structured vendors such as RavenPack or MarketPsych, direct social/search sources such as X, Reddit, Stocktwits, and search-trend feeds, alternative sources such as Quiver, and web discovery/ingestion such as Firecrawl. Provider names are not embedded in the decision logic.

## Observation model

Each `BehavioralObservation` records permanent `security_id`, provider ID, upstream independence group, source class, observation window, received time, mention counts, directional mention counts, unique authors, sentiment, attention, fear, uncertainty, novelty, relevance, confidence, spam risk, bot risk, source version, and provenance.

Every observation remains research-only with trading and live-trading authorization disabled.

## Integrity and point-in-time controls

The engine rejects observations received after the evaluation boundary. Stale observations and observations below relevance/confidence thresholds or above spam/bot-risk thresholds are excluded with visible reason codes.

Only one observation per upstream `independence_group` is accepted for a window. Two APIs that ultimately represent the same upstream source do not count as independent confirmation.

## Canonical behavioral state

The engine emits a deterministic `BehavioralIntelligenceState` containing:

- sentiment level and change
- sentiment dispersion and regime
- attention level and change
- mention rate and mention acceleration
- attention regime: UNKNOWN / FALLING / QUIET / RISING / SURGING
- fear, uncertainty, and novelty levels
- independent-source and source-class diversity
- cross-platform directional confirmation
- accepted/excluded observation lineage
- explicit blockers and warnings

A missing baseline does not invent acceleration; it preserves the current state at warning grade. If no valid current observations remain, the state is BLOCKED and carries no canonical sentiment or attention level.

## Research Council integration

`BehavioralIntelligenceState.to_council_input_ref()` converts the state into governed Research Council evidence. This allows the Behavioral Analyst to cite the exact behavioral state ID used in its opinion.

The Behavioral Analyst still has no execution, portfolio-mutation, risk-limit, or live-trading authority. Behavioral evidence can affect research conviction and timing but cannot bypass the CIO, Portfolio Construction, Risk Governor, or Governance Lock.

## AWS deployment target

When external connectors are approved, the intended AWS path is:

`API/WebSocket connectors -> API Gateway/Kinesis/EventBridge -> normalization Lambdas -> S3 immutable raw/history -> canonical behavioral state -> Feature/Intelligence layer -> Behavioral Analyst -> Research Council -> CIO/Fusion`

Secrets belong in AWS Secrets Manager, connector health in CloudWatch, immutable lineage in S3, and current state in the platform's fast state store. This V1 PR does not deploy AWS resources or call external vendors.
