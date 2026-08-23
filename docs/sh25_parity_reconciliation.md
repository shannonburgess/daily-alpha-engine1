# SH25 challenger parity reconciliation

SH25 remains a separate `PAPER_SHADOW_V25` challenger stacked on the SH24 CONTROL parity branch.

Current integration target:

- authoritative main: `adeccd111a5fb5bdd0642637213bb91e062ee75a`
- current SH24 branch head: `bd42de8eebb8d09166b8b1ad2470fe9bc0a81f05`
- frozen SH25 strategy version: `2.5`
- frozen Pine source blob: `2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5`
- archived SH25 source SHA-256: `77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718`
- Pine execution semantics: `process_orders_on_close=true`

The current SH24 branch contains authoritative main plus the complete SH24 parity stack. SH25 validates as a synthetic merge against that exact base rather than copying product-surface, adaptive-model-training, or future execution authority into the challenger. SH24 and SH25 books, parameters, source lineage, events and performance remain isolated.

The latest complete deployed forward-monitor receipt is the issue #213 `DAILY_ALPHA_FORWARD_PARITY_DEPLOYMENT_RECEIPT_V1` from workflow run `32670324393` on exact main `adeccd111a5fb5bdd0642637213bb91e062ee75a`. The Pine processor update is `Successful` and the bounded event sets are complete/non-truncated. The genuine SH25 TradingView event is DINO at 2026-08-21 20:00 UTC, price 97.32, `ENTRY_LONG / NORMAL_BREAKOUT`, with downstream `NO_TRADE / SECTOR_DATA_UNVERIFIED`. The three 2026-08-19 SH25 ADD E2E IDs remain immutable audit history but are excluded by exact ID from genuine forward parity candidates. The receipt proves persisted source-event evidence and book inspection; it does not prove Pine/Python parity.

Historical and forward parity remain unproven until exact point-in-time OHLCV + earnings-known-at evidence and the complete machine-readable v2.5 Pine input manifest are available. Synthetic/favorable replacement data is not accepted, and TradingView remains frozen. Any discrepancy must be investigated in the Python translation or source inputs rather than by changing TradingView.

Safety remains fail-closed: new PAPER entries are shares only; ORATS is research-only/nonblocking; `trading_authorized=false`; `live_trading_enabled=false`.
