# Daily Alpha R2 — Full Portfolio Defense Checkpoint

Research only. No production strategy, paper execution, Lambda, TradingView, broker, or live-trading state changed.

## Portfolio architecture tested

1. **R2 individual-stock sleeve — shares**
   - fresh 20-day breakout
   - ADX >=17 and rising
   - efficiency >=0.20
   - RSI <=80
   - strong-close filter >=0.65
   - bullish adaptive trend + two completed bullish trend bars
   - starter risk 0.50% NAV
   - +1 ATR and +2 ATR adds
   - hard close-based 0.75R risk cap
   - primary 55-day low trend exit

2. **Leveraged sector proxy sleeve — ETF shares**
   - only when no individual stock setup/open stock exposure exists in that sector
   - signal generated from unlevered sector ETF
   - persistent bullish sector trend: 3 bullish trend bars, ADX>=17 and rising, efficiency>=0.20, RSI<=80, close>SMA20
   - 2x default risk budget 0.35% NAV
   - 3x only for exceptional confirmation: ADX>=22, relative volume>=1.20, close-location>=0.70; risk budget 0.25% NAV
   - leveraged ETFs are execution vehicles, not signal sources
   - tested 5D, 10D and 20D exits

3. **Treasury reserve**
   - idle investable cash modeled using FRED DGS3MO Treasury carry net of a 0.09% SGOV fee proxy
   - used to avoid raw SGOV-price distortion from monthly distributions

4. **Drawdown throttle**
   - new-risk multiplier 1.00 above -5% drawdown
   - 0.75 at -5% to -8%
   - 0.50 at -8% to -12%
   - 0.25 at >=-12%

5. **Beta hedge diagnostic**
   - simple drawdown-triggered synthetic SPY short was tested and rejected; it materially damaged return by hedging after losses and fighting rebounds.

Options were deliberately excluded from this particular portfolio test to isolate stock shares + leveraged sector ETF shares + Treasury reserve + portfolio risk controls.

## Full portfolio run — 2022-01-01 through 2026-07-31

89 usable histories; MATL returned ORATS 404 and was omitted.

| Variant | CAGR | Ann Vol | Sharpe* | Sortino* | Max DD | Calmar | Worst month | Ending NAV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| R2 stocks + SGOV proxy | 9.42% | 17.66% | 0.37 | 0.52 | -23.19% | 0.41 | -10.96% | $1,886,471 |
| Fresh-sector 2x/3x + SGOV | 9.48% | 17.65% | 0.38 | 0.52 | -23.19% | 0.41 | -10.96% | $1,891,267 |
| Fresh-sector + drawdown throttle | 12.05% | 16.88% | 0.52 | 0.72 | -21.52% | 0.56 | -13.61% | $2,103,248 |
| Fresh-sector + throttle + simple SPY hedge | 3.11% | 14.18% | 0.00 | 0.01 | -21.55% | 0.14 | -13.74% | $1,437,644 |

*Sharpe/Sortino calculated versus the modeled Treasury-reserve daily rate.

The fresh-sector trigger fired too rarely, so a persistent sector-leadership test was run next.

## Persistent sector sleeve

| Variant | CAGR | Sharpe* | Sortino* | Max DD | Calmar | Worst month | Ending NAV | 2x entries | 3x entries |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Stock only | 9.42% | 0.37 | 0.52 | -23.19% | 0.41 | -10.96% | $1,886,471 | 0 | 0 |
| 2x/3x sector, 5D exit | 6.45% | 0.22 | 0.30 | -23.19% | 0.28 | -10.96% | $1,663,403 | 12 | 0 |
| **2x/3x sector, 10D exit** | **13.03%** | **0.52** | **0.73** | -23.19% | **0.56** | **-18.01%** | **$2,187,949** | 8 | 1 |
| 2x/3x sector, 20D exit | 9.75% | 0.39 | 0.54 | -23.19% | 0.42 | -12.47% | $1,912,923 | 10 | 3 |
| **10D sector + DD throttle** | **11.95%** | **0.52** | **0.72** | **-21.62%** | **0.55** | **-13.52%** | **$2,094,715** | 15 | 3 |

## Current interpretation

- **Shares remain the core R2 vehicle.**
- **SGOV/Treasury reserve remains structurally sensible** for idle investable cash.
- **Persistent sector leadership is the correct concept**; requiring a same-day fresh sector breakout was too restrictive.
- **10-day leveraged-sector exit is the only tested horizon with a material return benefit**, raising CAGR from 9.42% to 13.03% in this diagnostic.
- That return came with a materially worse worst month (-18.01%), so the raw 10D leveraged sleeve is **not yet production-ready**.
- Drawdown throttling reduced the 10D sleeve's max drawdown from -23.19% to -21.62% and improved the worst month to -13.52%, but also reduced CAGR to 11.95%.
- The simple drawdown-triggered SPY hedge is rejected. A future beta hedge must be regime-aware (e.g. market trend/breadth/beta), not triggered only after portfolio drawdown.
- 3x exposure remained rare under the exceptional-confirmation rule, which is desirable; the model should not force 3x usage.

## Next research requirement

Before promotion, test the 10D leveraged-sector sleeve across a larger sector/ETF universe and add a regime-aware risk gate that can protect the -18% worst-month behavior without eliminating the return improvement. Keep stock and leveraged-ETF risk budgets combined at the portfolio level; do not stack leverage on top of an already-full sector risk allocation.
