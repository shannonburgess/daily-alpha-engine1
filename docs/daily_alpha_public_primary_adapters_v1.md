# Daily Alpha Public Primary-Source Adapters V1

## Purpose

Stage 9A introduces deterministic request builders and payload normalizers for the first public/reference sources in the institutional data stack. Network transport is intentionally excluded from this stage so captured payloads can be replayed, validated, and versioned before AWS or credentialed connectors are enabled.

## Sources

### OpenFIGI

Reference endpoint: `POST https://api.openfigi.com/v3/mapping`.

The adapter builds mapping jobs using `idType` and `idValue` and normalizes returned FIGI, composite FIGI, share-class FIGI, ticker, issuer/name, security type, market sector, and exchange code. OpenFIGI remains reference/identity evidence; it does not silently replace the Daily Alpha permanent `security_id`.

OpenFIGI can be queried without an API key at lower rate limits. V1 therefore does not embed or require a secret in the request specification.

### SEC EDGAR submissions

Reference endpoint: `GET https://data.sec.gov/submissions/CIK##########.json` using a zero-padded 10-digit CIK.

The SEC adapter normalizes recent filing metadata including accession number, form, filing date, report date, acceptance timestamp, primary document, and primary-document description. Filing evidence is emitted as `DataDomain.SEC_FILINGS` with `REGULATOR_PRIMARY` provenance.

SEC EDGAR submissions are treated as primary regulatory evidence. V1 performs no scraping of filing body text and does not infer facts that are absent from the SEC payload.

### FRED / ALFRED semantics

Reference observations endpoint: `GET https://api.stlouisfed.org/fred/series/observations`.

Point-in-time requests explicitly set `realtime_start` and `realtime_end` to the evaluation date. This uses the FRED/ALFRED real-time-period model rather than today's revised historical value. The adapter preserves observation date, real-time start/end, and value.

Missing FRED values represented by `.` are emitted as `DATA_ERROR`, never silently converted to zero.

FRED requires an API key. V1 stores only the logical secret reference `FRED_API_KEY`; the secret value is never present in the request specification, fixture, repository, or deterministic request ID.

## Transport boundary

`HttpRequestSpec` contains method, HTTPS URL, sorted query parameters, optional JSON body, and a logical secret reference. It contains no credential value and makes no network call.

Future AWS transport can implement:

`EventBridge / Step Functions -> connector Lambda -> Secrets Manager -> HTTPS API -> raw response S3 -> deterministic adapter -> canonical evidence`

This allows retries, rate-limit handling, User-Agent policy, backoff, source-health metrics, raw response retention, and parser versioning to be added without changing downstream research contracts.

## Point-in-time and lineage rules

- HTTPS only.
- Request IDs are deterministic.
- SEC received time cannot precede filing acceptance time.
- FRED vintages after the evaluation boundary are rejected.
- OpenFIGI mappings retain their own mapping IDs and do not become permanent Daily Alpha identity by themselves.
- Every emitted provider observation retains provider ID, independence group, source version, authority provenance, and exact source-record identity.

## Scope boundary

No external API is called by this PR. No API key is purchased or stored. No AWS deployment, broker connection, TradingView mutation, PAPER mutation, capital authorization, execution authorization, or live trading is introduced.
