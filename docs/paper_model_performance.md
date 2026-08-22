# Daily Alpha PAPER Model-Validation Performance Contract

This contract measures whether the Daily Alpha model works before instrument optimization.
It is observability/research only and does not authorize or route a trade.

## Canonical books

Keep the two forward books separate:

- `PAPER_SHADOW_V24` — SH24 CONTROL
- `PAPER_SHADOW_V25` — SH25 CHALLENGER

A genuine rejection/no-trade observation is recorded separately and never increments trade `N`.

## Stock-primary fill semantics

New model-validation observations are STOCK/shares only. The entry basis is
`CONFIRMED_SIGNAL_PRICE_MODEL_VALIDATION`, matching the approved stock-primary semantics for a
fresh confirmed Pine/scanner event. This is an internal PAPER accounting fill and must never be
represented as a brokerage fill.

ORATS/options are outside this performance contract and cannot authorize, reject, delay, or block
a STOCK PAPER entry.

## Required reporting

For each book, report when evidence exists:

- closed-trade `N`, wins/losses/breakeven and win rate;
- cumulative model P/L;
- average winner and average loser;
- profit factor;
- cumulative R, expectancy/R and average winner/loser in R;
- maximum drawdown in model P/L and R;
- MFE/MAE and evidence coverage;
- average holding period;
- slices by setup type, lifecycle stage, sector and industry;
- rejection/no-trade counts by exact reason code.

Risk, MFE and MAE fields are not reconstructed when absent. Coverage is explicit, and incomplete
R evidence is labeled `R_EVIDENCE_INCOMPLETE` rather than silently treated as zero.

## Evidence interpretation

- `NO_CLOSED_TRADES`: no performance conclusion is available.
- `R_EVIDENCE_INCOMPLETE`: some closed trades lack initial-risk evidence; R-based statistics are
  descriptive only over the observed subset.
- `SMALL_SAMPLE_DESCRIPTIVE_ONLY`: complete R evidence exists but fewer than 30 closed trades are
  available; do not promote a strategy/filter change from this sample.
- `DESCRIPTIVE_FORWARD_EVIDENCE`: at least 30 closed trades with complete R evidence exist. This
  still does not authorize promotion; walk-forward/model-governance review remains separate.

The scorecard always emits `promotion_authorized=false`, `trading_authorized=false`, and
`live_trading_enabled=false`.
