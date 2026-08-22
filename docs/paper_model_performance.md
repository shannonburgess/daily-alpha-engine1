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

## Runner-aware P/L and R

The existing PAPER lifecycle can add to a winner and later harvest part of the position before the
final exit. Therefore a closed trade must not be scored only as `(final exit - current average
entry) * remaining shares`. That shortcut can omit earlier ADD/PARTIAL economics and materially
misstate expectancy.

When canonical ledger evidence is available, use:

- `realized_pnl` from the closed durable trade as total model P/L, because it already includes
  prior partial realization plus the final close leg;
- `initial_risk_basis` from the entry pipeline as the total original model-risk denominator;
- full-trade R = `realized_pnl / initial_risk_basis`.

The scorecard reports canonical realized-P/L coverage explicitly. It may fall back to simple
entry/exit arithmetic only for legacy/simple observations that do not claim a total risk basis.
A total `initial_risk_basis` without canonical cumulative realized P/L fails closed rather than
mixing incompatible denominators.

MFE/MAE is not reconstructed from runner state. It is reported only when compatible path/risk
evidence actually exists.

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
- canonical cumulative-realized-P/L coverage;
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
