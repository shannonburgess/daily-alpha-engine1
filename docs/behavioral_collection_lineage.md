# Behavioral Change Collection Lineage Gate

This is a research-only boundary for issue #219. It exists so a future scheduled collection job cannot silently change providers, entity mappings, storage layout, quota limits, or credential handling while historical evidence continues to look comparable.

## Frozen before scheduling

Each collection run must bind to a deterministic `BehavioralCollectionLineage` containing:

- exact point-in-time `as_of` timestamp;
- version and SHA-256 of the exact entity dictionary bytes;
- versioned provider adapter contract for Google Trends, YouTube and Similarweb;
- explicit provider configuration/access state and bounded query ceiling;
- cache scope;
- an opaque credential reference only, never a credential value;
- immutable artifact schema/root contract;
- `research_only=true`, `trading_authorized=false`, `live_trading_enabled=false`.

Google Trends remains `DISABLED`/unconfigured until approved alpha access exists. Similarweb remains optional/unconfigured unless existing API access is explicitly provided. YouTube may reference the existing AWS Secrets Manager path, but the secret value must never enter repository evidence.

## Collection receipt

A completed research collection binds all declared provider statuses plus the immutable observation/snapshot hashes back to the lineage ID. The binding fails closed when:

- a provider result is missing, duplicated, or undeclared;
- an unconfigured provider reports `COMPLETE`;
- a supposedly complete provider carries an error reason;
- an observation comes from an undeclared source or after the point-in-time cutoff;
- observation entity/ticker does not match the snapshot;
- research/live safety flags drift;
- immutable artifact hashes are absent.

The receipt is deterministic and order-independent across provider-result ordering.

## Explicit non-goals

This contract does not schedule a job, deploy AWS production, enable TradingView, authorize a PAPER/live trade, purchase data, or promote any Behavioral factor. Scheduling and storage publication remain a later reviewed step after this lineage contract and its tests are green.
