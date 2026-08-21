# Daily Alpha Agentic Intraday V1 — MU TradingView Sensor

This directory contains the **separate MU-only TradingView sensor layer** for issue #257. It is isolated from the frozen SH24/SH25 swing scripts and must never be substituted into those alerts.

## Files

- `mu_agentic_15m_context_v1.pine` — 15-minute context sensor during the U.S. regular session.
- `mu_agentic_2m_opening_v1.pine` — 2-minute opening sensor. Builds the 09:30-09:36 ET opening range and emits confirmed bars from 09:36-10:00 ET.
- `mu_agentic_5m_continuation_v1.pine` — 5-minute continuation sensor from 10:00-15:30 ET.

All three scripts are indicators, not strategies. They contain no `strategy.entry`, `strategy.close`, broker route, options route, SH24/SH25 mutation, or live-trading authorization.

## V1 sensor contract

The Pine layer emits **point-in-time market observations only**. The server remains authoritative for:

- Daily Alpha daily-context approval;
- persistence of the most recent valid 15M context state;
- sector-context reconciliation;
- scheduled macro blackout state;
- earnings/event-risk state;
- canonical company liquidity verification;
- portfolio/account state and risk sizing;
- deterministic 2M/5M signal evaluation;
- PAPER model-validation fills and receipts;
- mandatory flattening;
- all `trading_authorized=false` / `live_trading_enabled=false` controls.

Every Pine payload contains `requires_server_enrichment=true`. A sensor message alone can never authorize a PAPER entry.

## Forward-test candidate configuration

The branch currently uses these explicit V1 research choices:

- symbol: `MU` only;
- sector proxy: `AMEX:SOXX` by default;
- 15M context: MU above VWAP, EMA9 > EMA20, positive MU-vs-SOXX one-bar relative strength; sector context requires SOXX close > EMA9 > EMA20;
- 2M opening range: 09:30-09:36 ET;
- 2M emission window: 09:36-10:00 ET;
- 5M emission window: 10:00-15:30 ET;
- 5M continuation reference: prior 3-bar high by default;
- relative volume: current bar volume / prior 20-bar average;
- 30D average daily share volume: prior completed daily-bar 30-day average.

These are **candidate sensor definitions**, not optimized claims. Freeze them before the first forward test and do not retune them from a small sample.

## Alert setup boundary

Do not create TradingView alerts until the Stage-6 intraday ingress/aggregation contract is merged and its staging endpoint is verified. When that backend is ready, each script should use a TradingView alert configured as **Any alert() function call**, with the script's `Enable sensor alert() messages` input enabled and the dedicated intraday webhook secret entered locally in TradingView.

No secret belongs in GitHub.

## Safety

PAPER/research only. No live capital, broker integration, options, overnight position, averaging down, AWS production deployment, or SH24/SH25 TradingView mutation. The dedicated account remains `PAPER_AGENTIC_INTRADAY_V1`.
