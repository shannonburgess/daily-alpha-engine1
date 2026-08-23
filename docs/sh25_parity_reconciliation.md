# SH25 challenger parity reconciliation

SH25 remains a separate `PAPER_SHADOW_V25` challenger stacked on the SH24 CONTROL parity branch.

Current integration target:

- authoritative main: `e8a14a716d2eecdb79427250ea5861b5ea681c69`
- current SH24 branch head: `948d157df2ceef9cacbd19ff6c5ca90fed688425`
- frozen SH25 strategy version: `2.5`
- frozen Pine source blob: `2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5`
- archived SH25 source SHA-256: `77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718`
- Pine execution semantics: `process_orders_on_close=true`

The current SH24 branch now contains authoritative main plus the complete SH24 parity stack. SH25 must validate as a synthetic merge against that exact base rather than copying product-surface, adaptive-model-training, or future execution authority into the challenger. SH24 and SH25 books, parameters, source lineage, events and performance remain isolated.

The latest complete deployed forward-monitor receipt remains the issue #213 receipt from main `9fd6affcbdd7914ff611b029103c95794c7ed3bb`. It proves the genuine DINO TradingView event exists in SH25 at 2026-08-21 20:00 UTC, price 97.32, `NORMAL_BREAKOUT`, with downstream `NO_TRADE / SECTOR_DATA_UNVERIFIED`; it does not prove Pine/Python parity.

Historical and forward parity remain unproven until exact point-in-time OHLCV + earnings-known-at evidence and the complete machine-readable v2.5 Pine input manifest are available. Synthetic/favorable replacement data is not accepted, and TradingView remains frozen.

Safety remains fail-closed: new PAPER entries are shares only; ORATS is research-only/nonblocking; `trading_authorized=false`; `live_trading_enabled=false`.
