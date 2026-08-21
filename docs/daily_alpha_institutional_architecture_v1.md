# Daily Alpha Institutional Architecture V1

## Mission

Daily Alpha is evolving from a deterministic research/PAPER trading system into a
multi-agent quantitative investment operating system. The institutional design target is
not an autonomous chatbot that trades. It is a governed system in which deterministic
market/account facts, point-in-time evidence, independent research agents, portfolio
construction, risk controls, execution controls, and post-decision forensics are separate
layers with auditable contracts.

Issue #269 owns the Agentic Intelligence V1 foundation.

## Non-negotiable architecture principles

1. **Facts are deterministic.** Prices, positions, fills, NAV, liquidity, earnings dates,
   security classification and risk calculations come from authoritative code/data sources,
   never from LLM memory.
2. **Point-in-time only.** Evidence must have `observed_at` and `received_at` timestamps and
   cannot be used before it was actually available.
3. **Explicit failure states.** Sources report `COMPLETE`, `STALE`, `SOURCE_UNAVAILABLE`,
   `CONFLICT`, or `DATA_ERROR`. Missing data is never silently converted to zero/neutral.
4. **Immutable provenance.** Every evidence record has a deterministic identity derived from
   its exact source-attributed contents.
5. **Independent agents.** Research agents have narrow mandates and cannot mutate execution
   state directly.
6. **Adversarial review.** Bullish evidence is challenged by Bear/Skeptic/Risk agents rather
   than reinforced by multiple agents with the same mandate.
7. **Deterministic risk authority.** Existing liquidity, sector, earnings/event, concentration,
   portfolio-risk and account-safety controls remain authoritative.
8. **Evidence-gated promotion.** Research -> backtest -> PAPER/shadow -> limited live ->
   production requires measurable evidence; no model skips stages.
9. **Complete decision lineage.** A future `DECISION_ID` must reconstruct the evidence,
   model versions, portfolio state, risk calculation, order/fill and outcome.
10. **Vendor/model portability.** Agent intelligence should be replaceable without rewriting
    the deterministic trading core.

## Target system

```text
GLOBAL DATA FABRIC
        |
        v
SOURCE AGENTS
        |
        v
CANONICAL EVIDENCE LAYER
        |
        v
DATA SUPERVISOR
        |
        +------------------------------+
        |                              |
        v                              v
DETERMINISTIC QUANT ENGINES      RESEARCH/REASONING AGENTS
        |                        Momentum / Rotation / Catalyst
        |                        Fundamental / Behavioral / Macro
        |                        Bear / Skeptic / Risk
        +---------------+--------------+
                        |
                        v
                 CIO / SIGNAL FUSION
                        |
                        v
              PORTFOLIO CONSTRUCTION
                        |
                        v
              DETERMINISTIC RISK GOVERNOR
                        |
                        v
                EXECUTION CONTROLLER
                        |
                        v
                 PAPER / SHADOW BOOKS
                        |
                        v
                    FORENSICS
                        |
                        v
             FACTOR + AGENT ATTRIBUTION
                        |
                        v
                 MODEL GOVERNANCE
```

## Existing Daily Alpha components to reuse

The new agentic layer is an extension, not a rebuild. Existing authoritative components
remain below it:

- OVTLYR ingestion, classification and immutable dated history
- stock-primary shortlist and strict company-liquidity control
- server-authoritative sector context
- TradingView/Pine ingress and durable signal evidence
- PAPER account isolation, ledger state and exact receipts
- replay/idempotency and fail-closed monitoring controls
- newsletter/reporting surfaces
- factor/strategy forensics research foundations
- Agentic Intraday patterns for sensor/server authority separation and state isolation

## V1 foundation contracts

### Canonical evidence record

Every source agent must eventually emit the canonical `EvidenceRecord` contract:

- symbol
- evidence type
- value
- source
- observed timestamp
- received timestamp
- source version
- explicit status
- confidence
- reason code
- provenance metadata
- deterministic evidence/value hashes
- hard research/live safety flags

### Source registry

Every connected source must declare:

- source identity
- owner
- evidence types
- expected cadence
- maximum freshness
- required vs optional status
- fail-closed states
- whether cross-source agreement is mandatory

Sources cannot silently redefine these rules at runtime.

### Evidence store

The V1 in-memory store proves the semantic contract:

- idempotent insertion of identical evidence
- immutable logical source observations
- point-in-time retrieval
- deterministic latest-record selection

Later S3/DynamoDB implementations must preserve the same behavior.

### Data Supervisor

The supervisor does not trade. It evaluates whether the evidence package is trustworthy.
For every symbol it produces:

- PASS / WARNING / BLOCKED readiness
- source-by-source assessment
- completeness score
- freshness score
- data-confidence score
- exact blockers and warnings
- visible cross-source conflicts

A high-conviction research model may still be blocked when data readiness is inadequate.

## Development roadmap

### Stage 1 - Foundation
Canonical evidence contract, source registry, evidence store, supervisor and regression tests.

### Stage 2 - Existing-source adapters
Wrap, rather than rewrite, the existing OVTLYR, server-sector, company-liquidity and Pine
surfaces into canonical evidence agents.

### Stage 3 - Durable evidence persistence
Implement immutable S3 history plus current-state/query indexes while preserving the V1
point-in-time contract.

### Stage 4 - Additional data agents
Add governed Market Data, Earnings/Event, SEC, News/Catalyst, Macro, Fundamentals,
Institutional and Behavioral agents. User-directed option analysis remains a separate lane
using broker-chain data when explicitly supplied/authorized.

### Stage 5 - Quant research agents
Create independent Momentum, Rotation, Catalyst, Fundamental, Behavioral, Macro and
Relative-Strength research agents.

### Stage 6 - Adversarial investment committee
Add Bear, Skeptic and dedicated Risk agents. Their job is to identify contradictions,
missing evidence, crowding, event risk and loss scenarios.

### Stage 7 - CIO / signal fusion
Combine validated independent evidence without permitting the LLM layer to bypass hard
controls. Store every component score and reason code.

### Stage 8 - Portfolio construction
Rank opportunities by expected alpha versus marginal portfolio risk, incorporating
correlation, factor overlap, sector concentration, volatility, liquidity/capacity and
existing exposure.

### Stage 9 - Shadow/PAPER evaluation
Run the agentic decision system beside existing strategies first. No execution promotion
until attribution shows stable incremental value out of sample.

### Stage 10 - Attribution and governance
Bind every agent/model decision to 1D/5D/10D/20D outcomes, MFE, MAE, drawdown, relative
returns and regime/sector context. Promotion decisions use evidence, not anecdote.

## Safety boundary for V1

The Agentic Intelligence foundation is research/shadow only:

- no AWS deployment
- no TradingView mutation
- no broker route
- no live-capital change
- no SH24/SH25 parameter changes
- no automated option execution
- `trading_authorized=false`
- `live_trading_enabled=false`

The foundation must remain useful even if no LLM is connected. LLMs are an analysis layer
above canonical evidence, never the source of truth for trading facts.
