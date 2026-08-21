# Daily Alpha stock-primary PAPER validation

Effective decision date: 2026-08-20

## Objective

The current forward-test objective is to determine whether the Daily Alpha signal/model has positive, repeatable expectancy without allowing option-chain selection, option pricing, DTE/strike choice, or ORATS availability to obscure the result.

## Canonical PAPER execution policy

- New PAPER positions are **shares only**.
- A stock entry still requires the canonical Daily Alpha signal, lifecycle, sector, company-liquidity, portfolio-risk and other active safety gates.
- The broad server-side stock floor is $10. Frozen SH24/SH25 v2.4 Pine remains unchanged and retains its stricter $25 price floor.
- The confirmed Pine/scanner signal price is the PAPER model-validation fill. This mirrors the frozen v2.4 Pine strategy's `process_orders_on_close=true` semantics and must not be represented as a live brokerage fill.
- The validated stock stop carried by the signal is required for risk-based share sizing.
- Existing runner rules (ADD, PARTIAL/HARVEST, EXIT) continue on shares using the corresponding confirmed signal price.
- New OPTION positions are disabled.
- ORATS may continue to support newsletter/research intelligence. It cannot authorize, reject, or delay a new stock PAPER entry.
- If a legacy OPTION PAPER position exists during cutover, the previous fail-closed ORATS path may be used only to manage/close that already-open position so it is not stranded.
- `trading_authorized=false` and `live_trading_enabled=false` remain mandatory.

## Why this policy

This separates two questions that were previously mixed together:

1. **Does the Alpha Engine identify profitable entries/exits?**
2. **What instrument best expresses that edge?**

The current validation phase answers question 1 first. Options can be researched later as a separate instrument-overlay experiment using the same underlying signals.

## Required measurement

Every forward PAPER trade should retain model/strategy identity and be evaluated with at least:

- trade count (N)
- win rate
- expectancy in R
- average winner and average loser
- profit factor
- cumulative P/L and cumulative R
- maximum drawdown
- MFE and MAE when the required path data is available
- holding period
- results by entry/setup type
- results by lifecycle stage
- results by sector/industry
- SH24 CONTROL vs SH25 CHALLENGER, without mixing the books
- rejection/no-trade reasons so filters can be evaluated rather than assumed beneficial

No strategy rule should be promoted merely because of a small sample. Changes should be driven by forward evidence, robustness, drawdown, expectancy, and failure analysis.

## Scope

This is a PAPER model-validation policy only. It does not enable a live broker, authorize live capital, modify frozen TradingView Pine source, or deploy AWS production resources.
