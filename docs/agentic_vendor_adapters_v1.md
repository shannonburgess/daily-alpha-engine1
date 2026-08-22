# Agentic Intelligence V1 — Stage 9C Institutional Vendor Adapters

Stage 9C adds provider-specific normalization behind the Stage 9B AWS transport boundary. The implementation is fixture/shadow only: it builds deterministic request specifications, validates captured payloads, and emits provider-agnostic observations. It does not perform HTTP calls, resolve secret values, deploy AWS resources, activate paid plans, connect a broker, or authorize trading.

## Source contracts

### Massive Stocks

Daily Alpha uses the documented Stocks Custom Bars surface (`GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`) for OHLCV capture. The adapter accepts only completed bars, preserves the vendor request ID and optional VWAP/transaction count as provenance, and emits `MARKET_BARS / OHLCV` observations under independence group `MASSIVE_MARKET_DATA`.

The request specification carries only the logical secret name `MASSIVE_API_KEY`. No credential value is embedded in the URL, query, source, fixture, receipt, or log contract.

### Databento Historical

Daily Alpha models Databento Historical `timeseries.get_range` using JSON output, mapped symbols, pretty timestamps/prices, and the documented `ohlcv-1s`, `ohlcv-1m`, `ohlcv-1h`, and `ohlcv-1d` schemas. Databento `ts_event` is treated as the inclusive start of the bar interval; the schema suffix defines the interval length. JSON-lines transport is supported because Databento's HTTP JSON encoding is a record stream.

Databento is an independent market-data group (`DATABENTO_MARKET_DATA`) rather than false redundancy for Massive. The logical credential reference is `DATABENTO_API_KEY`.

### Financial Modeling Prep (FMP)

FMP stable endpoints are modeled for normalized income statements and analyst estimates. FMP is intentionally treated as vendor-normalized evidence rather than regulator/issuer primary evidence.

The analyst-estimates endpoint is a current consensus snapshot, not automatically a trustworthy historical revision tape. Daily Alpha therefore uses the immutable Stage 9B transport receipt time as the point-in-time known/publication boundary for every captured estimate snapshot. Replaying an archived response reproduces what the platform actually knew at capture time; it does not infer earlier historical availability from the forecast period-end date.

Income statements follow the same conservative capture-time rule. Filing/accepted-date fields are retained as provenance but do not by themselves upgrade FMP's normalized output to primary-authority evidence. The logical credential reference is `FMP_API_KEY`.

### Benzinga Newsfeed

Benzinga Newsfeed items are filtered by ticker and normalize into `NEWS_CATALYSTS / NEWS_ITEM` observations. Created and updated timestamps are preserved, symbol association is required, and future-dated items are rejected. Vendor news remains `SECONDARY` research authority even when delivered by a paid API. A later primary-source reconciler may separately corroborate the event against an issuer, exchange, or regulator document.

The request contract omits the API key and carries only logical secret name `BENZINGA_API_KEY`; production transport should inject the key via an authorization header rather than expose it in a URL.

## Stage 9B handoff

The vendor handoff consumes a `TransportResponseReceipt` and captured bytes. It requires:

1. a `SUCCESS` retry disposition;
2. an exact SHA-256/content-length match between receipt and body;
3. a provider ID consistent with the adapter route;
4. valid JSON (or JSON-lines for Databento);
5. provider-specific symbol, timestamp, shape, and point-in-time validation.

Only after those checks can the payload become a `ProviderObservation`. Malformed payloads, cross-symbol contamination, future/incomplete bars, future news, checksum tampering, and route/provider mismatches fail closed.

## Provider roles and independence

Massive is the preferred (`PRIMARY`) market-bar adapter and Databento is the independent (`SECONDARY`) verification adapter for the first market-data slice. These roles are Daily Alpha routing preferences, not claims that a vendor is a regulator/issuer primary source.

FMP is the preferred provider for normalized fundamentals/estimate snapshots in this initial contract. Benzinga is the preferred provider for vendor news/catalyst coverage. Research-fact authority is carried separately and remains `VENDOR_NORMALIZED` or `SECONDARY` as appropriate.

## AWS target path

The intended future runtime remains:

`EventBridge / Step Functions -> connector Lambda/consumer -> Secrets Manager -> provider -> immutable raw S3 archive -> SQS/DLQ -> Stage 9C adapter -> canonical provider observation -> reconciliation / research facts -> governed features and agents`

No runtime AWS resource is created by Stage 9C.

## Hard authority boundary

Every provider definition and observation remains `research_only=true`, `trading_authorized=false`, and `live_trading_enabled=false`. Stage 9C cannot mutate TradingView, SH24/SH25, PAPER ledgers, options automation, execution state, capital authorization, or live trading.

## Validation

The regression suite covers logical-secret-only request specs, documented request shapes, OHLCV normalization, Databento JSON-lines, symbol mismatch, incomplete/future bars, FMP capture-time semantics, false historical revision claims, Benzinga source authority, future news, checksum tampering, malformed payloads, route/provider mismatches, provider independence, and the no-trading authority boundary.
