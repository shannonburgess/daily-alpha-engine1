# Daily Alpha v2.5 — 10-Day vs 20-Day Breakout + R Expectancy

Research only. No production changes, broker calls, Lambda execution, or paper-ledger writes.

## Design
- Decision universe: 113 broad liquid U.S.-traded equities, excluding the 16 development names.
- Entry ADX frozen at validated v2.5 candidate: ADX >=17 AND rising.
- All other normal-entry gates unchanged: bullish adaptive trend, trend maturity, efficiency >=0.20, RSI <=80, price floor.
- Compared fresh normal breakout above prior 10-day high versus prior 20-day high.
- Earnings Gap & Go intentionally unchanged on existing 20-day behavior.
- Exits unchanged: failed breakout, Turtle-10, trend flip, +1/+2 ATR adds, +3ATR harvest, current post-harvest break-even.
- Canonical Daily Alpha 1R: initial two-unit risk from entry close to prior 10-day low.

## Decision-universe strategy results

| Period | Breakout | Gross deployed | Trades | Win rate | Profit factor | Positive symbols | Failed BO | Harvested |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 10D | -1.22% | 304 | 20.4% | 0.47 | 31/113 | 138 | 63 |
| 2022 | 20D | -1.16% | 300 | 21.0% | 0.48 | 33/113 | 136 | 63 |
| 2023 | 10D | +1.65% | 365 | 33.2% | 2.28 | 64/113 | 142 | 128 |
| 2023 | 20D | +1.63% | 365 | 33.2% | 2.22 | 64/113 | 141 | 127 |
| 2024-25 | 10D | +0.44% | 742 | 27.0% | 1.25 | 54/113 | 309 | 217 |
| 2024-25 | 20D | +0.52% | 728 | 26.9% | 1.29 | 52/113 | 307 | 208 |
| 2026 YTD | 10D | +0.59% | 235 | 32.3% | 1.28 | 52/113 | 98 | 73 |
| 2026 YTD | 20D | +0.50% | 236 | 31.8% | 1.22 | 52/113 | 100 | 71 |

## Win rate and R expectancy

| Period | Breakout | Trades | Win rate | Avg winner R | Avg loser R | Payoff | Expectancy R/trade |
|---|---|---:|---:|---:|---:|---:|---:|
| 2022 | 10D | 304 | 20.4% | 1.00R | 0.41R | 2.46x | -0.120R |
| 2022 | 20D | 300 | 21.0% | 0.99R | 0.39R | 2.51x | -0.103R |
| 2023 | 10D | 365 | 33.2% | 1.66R | 0.39R | 4.26x | +0.289R |
| 2023 | 20D | 365 | 33.2% | 1.60R | 0.39R | 4.08x | +0.269R |
| 2024-25 | 10D | 742 | 27.0% | 1.51R | 0.44R | 3.46x | +0.089R |
| 2024-25 | 20D | 728 | 26.9% | 1.53R | 0.44R | 3.45x | +0.088R |
| 2026 YTD | 10D | 235 | 32.3% | 1.38R | 0.43R | 3.23x | +0.157R |
| 2026 YTD | 20D | 236 | 31.8% | 1.35R | 0.43R | 3.15x | +0.137R |

### Combined 2022 through 2026 YTD
- 10D: 1,646 trades, 27.9% win rate, 1.46R average winner, 0.42R average loser, 3.48x payoff, +0.104R expectancy/trade.
- 20D: 1,629 trades, 27.9% win rate, 1.44R average winner, 0.42R average loser, 3.44x payoff, +0.100R expectancy/trade.

## LRCX diagnostic
With ADX >=17 and rising, LRCX's 10D and 20D variants generated the same 2026 trades and identical aggregate result. Key entries were Apr 14 at 272.22, May 6 at 296.96, and Jun 11 at 362.26 under both breakout horizons. Therefore the earlier LRCX capture came from the ADX change, not from shortening the breakout length.

## Decision
The 10-day breakout is not clearly superior enough to replace the 20-day breakout globally. It has a modest recent advantage (2026 YTD expectancy +0.157R vs +0.137R and PF 1.28 vs 1.22), but it was worse in 2022 and slightly weaker on profit factor/gross-deployed return in 2024-25. Across the full 2022-2026 YTD sample, expectancy differs by only +0.004R per trade (0.104R vs 0.100R).

Recommended architecture: retain 20D as the canonical normal breakout for the v2.5 production candidate. Treat 10D as a research/early-entry watch sleeve only if later tests identify a distinct subset where it adds value. Do not change production on this study alone.
