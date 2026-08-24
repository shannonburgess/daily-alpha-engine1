# Prospective realized-R label evidence V1

## Purpose

This contract supplies trustworthy realized-R labels for the research-only model-training path without retroactively backdating present-day market data.

The label adapter is intentionally prospective. It accepts only immutable `CURRENT_WINDOW` market-feed receipts from Massive or Tiingo. Historical backfill captures are rejected even when they contain old prices, because a payload downloaded later does not prove that the system knew those values at the original historical decision boundary.

## Evidence contract

A label requires two separately validated immutable market evidence objects:

1. entry evidence captured no later than the declared decision timestamp; and
2. outcome evidence actually captured only after the declared label horizon has matured.

Both evidence objects must target the same security and use the same supported market-data provider. Exact raw bytes are verified against the staging receipt SHA-256 and byte count through the existing `ImmutableFeedEvidence` contract.

The adapter does not accept caller-supplied realized R. It derives realized R mechanically from direction, entry price, exit price and initial per-share risk:

- LONG: `(exit_price - entry_price) / initial_risk_per_share`
- SHORT: `(entry_price - exit_price) / initial_risk_per_share`

Entry price, exit price and initial risk must be finite and positive. The entry source timestamp cannot occur after the decision boundary. The exit source timestamp cannot precede `decision_at + horizon_days` and cannot occur after the immutable outcome capture.

The resulting `RealizedRLabelObservation.known_at` is always the actual outcome receipt `captured_at` timestamp. It is never inferred from the historical observation date and cannot be rewritten earlier.

## Self-validating packet boundary

`ProspectiveRealizedRLabelPacket` is an evidence object, not a convenience container. Its constructor independently revalidates the complete relationship among the label, declared inputs and both immutable evidence records even when a caller bypasses `build_prospective_realized_r_label` and attempts to construct the dataclass directly.

The packet fails closed if any caller attempts to:

- rewrite `realized_r` away from the mechanically derived LONG/SHORT value;
- rewrite label `known_at` away from the exact outcome receipt capture timestamp;
- replace or omit either immutable entry/outcome evidence ID;
- rewrite the deterministic label source revision;
- pair entry and outcome evidence from different providers;
- use a target inconsistent with the declared security;
- move entry evidence after the decision boundary or outcome evidence before horizon maturity; or
- introduce historical-backfill evidence or any action authority.

This makes the lineage invariant durable at the object boundary rather than depending on every caller using the public builder correctly.

## Lineage

Each label retains both immutable entry and outcome evidence IDs. Its source revision is deterministically derived from both evidence source revisions plus the declared entry and exit source timestamps. The packet identity additionally binds the security, decision timestamp, horizon, direction, prices and initial risk.

This gives the dataset assembler a label that can be audited back to exact raw market evidence on both sides of the outcome calculation.

## Scope and limitations

This V1 contract proves label evidence integrity; it does not claim that the currently configured staging feeds have already accumulated enough prospective observations for model fitting. It also does not convert a historical download performed today into historical knowledge.

A genuine empirical experiment still requires a sufficient population of point-in-time feature rows and matured prospective labels, followed by the existing strict `TRAIN -> VALIDATION -> untouched TEST` protocol.

## Safety

This layer is research-only. `retuning_authorized=false`, `promotion_authorized=false`, `paper_mutation_authorized=false`, `trading_authorized=false`, and `live_trading_enabled=false`. It does not mutate SH24/SH25, TradingView, PAPER state, brokerage routes, production AWS, or capital authority.
