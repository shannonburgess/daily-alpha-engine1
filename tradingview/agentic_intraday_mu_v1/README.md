# Daily Alpha Agentic Intraday V1 — MU TradingView Sensor

The canonical Stage-5 TradingView source is:

- `tradingview/da_agentic_intraday_mu_v1_sensor.pine`

It is a **single MU-only indicator** that runs on separate 15M, 2M and 5M MU charts and emits raw point-in-time telemetry to the future Agentic Intraday ingress. It is isolated from the frozen SH24/SH25 swing scripts and must never be substituted into those alerts.

## Why one sensor source

One raw sensor source avoids competing Pine implementations while preserving timeframe-specific behavior:

- **15M** — regular-session context telemetry only;
- **2M** — telemetry only during 09:30-10:00 ET;
- **5M** — takes over at 10:00 ET, continues through 15:30 ET entries, 15:30-15:50 management-only telemetry, and 15:50-16:00 flatten telemetry.

The Pine source intentionally does **not** freeze an opening-range or continuation-breakout definition. Instead it emits the raw prior-high/low/session evidence needed by the backend so Stage 2 remains the sole deterministic signal authority.

## Raw telemetry

Confirmed-bar payloads include:

- OHLCV;
- VWAP;
- EMA9 / EMA20;
- same-timeframe relative volume;
- prior-completed-day 30D average daily share volume;
- MU relative strength versus QQQ and SMH;
- prior session high/low context;
- session bar count;
- prior 3/5/10-bar highs and prior 3/5-bar lows;
- authoritative session phase and timeframe;
- stable event identity.

Every payload is hard-bound to `MU`, `STOCK`, and `PAPER_AGENTIC_INTRADAY_V1`, with `sensor_only=true`, `paper_only=true`, `trading_authorized=false`, and `live_trading_enabled=false`.

## Server authority

The sensor never decides whether a trade is allowed. The backend remains authoritative for:

- Daily Alpha / OVTLYR daily context;
- latest valid 15M context persistence;
- sector-context admission;
- scheduled macro blackout state;
- earnings/event-risk state;
- canonical company liquidity and freshness;
- deterministic 2M/5M signal rules;
- portfolio state and risk sizing;
- PAPER model-validation fills and receipts;
- mandatory flattening and forensics.

A sensor message alone can never authorize a PAPER entry.

## Alert setup boundary

Do **not** create TradingView alerts yet. Stage 6 must first merge the isolated intraday ingress/enrichment path and verify its staging endpoint end-to-end.

After that backend is ready, use the same Pine source on three MU charts (15M, 2M and 5M), enable `Enable PAPER Sensor Alerts`, enter the dedicated intraday webhook secret locally in TradingView, and create each alert using **Any alert() function call**.

No secret belongs in GitHub.

## Safety

PAPER/research only. No live capital, broker integration, options, overnight positions, AWS production deployment, SH24/SH25 source/alert mutation, or live-trading authorization.
