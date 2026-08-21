# Daily Alpha Engine

Auditable research and PAPER-trading engine for the Daily Alpha workflow.

> **Current stage:** research and PAPER model validation only. No live brokerage execution.

## Current operating architecture

Daily Alpha now uses three separate lanes:

1. **Swing systematic PAPER** — SH24 CONTROL and SH25 CHALLENGER, stock/shares only for model validation.
2. **Agentic Intraday PAPER** — isolated MU pilot, stock/shares only, deterministic risk controls, no overnight positions.
3. **User-Directed Options** — options are never opened autonomously. The user explicitly authorizes every BUY/SELL decision and supplies broker-chain contract data when needed.

External options-data vendors are not part of trade authorization, rejection, sizing, or execution.

## Swing decision flow

1. Ingest and validate the daily OVTLYR universe.
2. Evaluate the frozen TradingView/Pine signal semantics.
3. Apply canonical company liquidity, price, event-risk, and portfolio-risk gates.
4. Record eligible STOCK PAPER model-validation fills and exact receipts.
5. Track SH24 and SH25 independently for forward-test evidence.

## Agentic Intraday V1

The isolated intraday pilot uses:

- account `PAPER_AGENTIC_INTRADAY_V1`
- MU only initially
- shares only
- long-only V1
- 2-minute opening execution window
- 5-minute standard/management window
- mandatory flat book by the close
- no averaging down
- no options
- `trading_authorized=false`
- `live_trading_enabled=false`

## User-Directed Options

Daily Alpha may help evaluate the underlying setup, risk, contract terms, and position tracking, but every option order requires an explicit user instruction. Contract details such as strike, expiration, bid/ask, IV, delta, open interest, and volume come from the user's broker chain rather than an automated vendor dependency.

## Included capabilities

- OVTLYR-style CSV normalization and validation
- TradingView/Pine signal ingestion
- company liquidity and portfolio risk controls
- stock-primary PAPER ledgers and execution receipts
- SH24/SH25 shadow model validation
- isolated Agentic Intraday V1 architecture
- research, monitoring, diagnostics, and failure controls
- Daily Alpha newsletter/reporting workflows
- reproducible quantitative research and model-governance tooling

## Local setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Validate a daily CSV:

```bash
daily-alpha path/to/ovtlyr.csv
```

## Data and secrets

- Put local daily files in `data/incoming/`; contents are ignored by Git.
- Generated research outputs belong in `data/output/`; contents are ignored by Git.
- Never commit brokerage credentials, webhook secrets, account numbers, or `.env` files.
- Required service credentials must be supplied through environment variables or managed secret stores.
- No external options-data vendor token is required by the current architecture.

## Safety

This software is for research and PAPER model validation. It does not authorize live trading and does not place live brokerage orders.
