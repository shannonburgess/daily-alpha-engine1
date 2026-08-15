# Daily Alpha Engine

Auditable research and paper-trading engine for the Daily Alpha workflow.

> **Current stage:** research and paper trading only. No live brokerage execution.

## Decision flow

1. Ingest the daily OVTLYR master-universe CSV.
2. Evaluate the approved Pine/Turtle entry or exit signal.
3. Apply the portfolio risk gate.
4. Validate ORATS option data freshness and availability.
5. Select a qualified option when DTE, spread, bid, open interest, and volume pass.
6. If valid option data contains no qualified contract, allow an independently eligible liquid stock paper trade.
7. If ORATS/API data is stale or unavailable, return `DATA_ERROR` and never substitute stock.
8. Store `instrument_selected`, `fallback_reason`, and the full decision for audit.

The enforced hierarchy is:

```text
qualified option -> eligible liquid stock -> no trade
```

## Included in the initial build

- typed option and stock decision models
- configurable option-quality and stock-liquidity rules
- OPTION → STOCK fallback engine
- explicit stale-data safety behavior
- append-only JSON Lines audit writer
- OVTLYR-style CSV normalization and validation
- command-line CSV validation
- automated unit tests and GitHub Actions

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
- Never commit ORATS tokens, brokerage credentials, account numbers, or `.env` files.
- API credentials will be supplied through environment variables or a managed secrets store.

## Next milestones

1. ORATS client with freshness checks and contract normalization
2. Pine/TradingView signal ingestion
3. portfolio sizing and risk-budget service
4. option and stock paper-trade ledgers tracked separately
5. shared Pine/Turtle exit handling
6. daily comparison against the prior OVTLYR universe
7. readable Daily Alpha newsletter and PDF generation
8. scheduling, monitoring, and failure alerts

## Disclaimer

This software is for research and paper trading. It does not provide investment advice and does not place live trades.
