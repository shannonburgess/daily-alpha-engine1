# Daily Alpha 16-Stock ADX / Post-3ATR Runner Study

Research only. March 1 through July 31, 2026. No production changes and no paper-ledger writes.

Test universe: LRCX, MU, FTI, IRM, RCMT, HUBB, ALGN, HUM, MRK, PSX, VLO, PLTR, SNDK, JNJ, HOOD, C.

Grid:
- ADX >=17 and rising on entry (runner/add gate >=17)
- ADX >=20
- ADX >=25 (current v2.4)
- CURRENT_BE: current post-3ATR average-cost break-even floor
- NO_BE_TURTLE_TREND: no post-harvest floor; Turtle-10/trend flip only
- TRAIL_2ATR: after +3ATR harvest, trail runner at highest close since harvest minus 2 base ATR
- TRAIL_3ATR: after +3ATR harvest, trail runner at highest close since harvest minus 3 base ATR

Returns below are underlying-strategy backtest returns on gross deployed units, not historical option-contract returns.

| Symbol | Buy/Hold | Current v2.4 | Best Tested Tradable | Best ADX | Best Post-3ATR Exit | Improvement | Trades/Wins |
|---|---:|---:|---:|---|---|---:|---:|
| LRCX | 27.09% | -7.05% | 14.05% | 17_RISING | TRAIL_3ATR | +21.10pp | 2/1 |
| MU | 99.56% | 41.61% | 55.19% | 17_RISING | CURRENT_BE | +13.57pp | 1/1 |
| FTI | 6.32% | -0.21% | -0.21% | 25 | CURRENT_BE | +0.00pp | 1/0 |
| IRM | 12.54% | -2.53% | 3.03% | 17_RISING | TRAIL_2ATR | +5.56pp | 1/1 |
| RCMT | 48.66% | 1.39% | 1.39% | 17_RISING | CURRENT_BE | +0.00pp | 1/1 |
| HUBB | -8.32% | 0.00% | -1.71% | 20 | CURRENT_BE | -1.71pp | 2/0 |
| ALGN | -10.51% | 0.00% | 0.00% | 25 | CURRENT_BE | +0.00pp | 0/0 |
| HUM | 95.73% | 63.51% | 63.51% | 20 | CURRENT_BE | +0.00pp | 1/1 |
| MRK | 8.81% | 0.00% | 0.00% | 25 | CURRENT_BE | +0.00pp | 0/0 |
| PSX | 33.11% | -2.88% | -1.20% | 17_RISING | CURRENT_BE | +1.68pp | 4/1 |
| VLO | 46.85% | 1.94% | 7.49% | 17_RISING | TRAIL_2ATR | +5.55pp | 2/2 |
| PLTR | -15.23% | 0.00% | -3.83% | 20 | CURRENT_BE | -3.83pp | 1/0 |
| SNDK | 96.23% | 34.88% | 84.62% | 17_RISING | CURRENT_BE | +49.74pp | 1/1 |
| JNJ | 3.73% | -2.23% | -2.23% | 17_RISING | CURRENT_BE | +0.00pp | 2/0 |
| HOOD | 9.88% | -8.40% | -0.90% | 17_RISING | CURRENT_BE | +7.50pp | 2/1 |
| C | 19.41% | 0.18% | 1.21% | 17_RISING | CURRENT_BE | +1.03pp | 1/1 |

Approximate mean current-v2.4 return across the 16 names: 7.52%.
Approximate mean best-per-symbol tested return: 13.78%.
If a rational NO-TRADE floor of 0% is applied when every tradable grid variant is negative, the in-sample best-per-symbol mean is about 14.41%.

Important: the best-per-symbol column is an in-sample diagnostic and must not be interpreted as an investable portfolio return. Choosing a different rule after seeing each stock's outcome is overfit. The next decision must be based on a single common rule evaluated out of sample / across a wider universe.

Key findings:
1. ADX >=17 and rising was the best entry mode on LRCX, MU, IRM, RCMT, PSX, VLO, SNDK, JNJ, HOOD and C in the tested grid (though several still produced negative returns). It materially improved LRCX, MU, IRM, VLO, SNDK, HOOD and C.
2. ADX >=20 remained best for HUM and was the best tradable threshold for HUBB and PLTR, although HUBB/PLTR's tested trades were negative and should rationally remain NO TRADE.
3. ADX >=25 remained adequate/best for FTI and no-trade ALGN/MRK in this window.
4. Completely removing the post-3ATR break-even floor (NO_BE_TURTLE_TREND) was not the best variant for any of the 16 stocks.
5. A wider runner materially improved three leaders: LRCX preferred TRAIL_3ATR; IRM and VLO preferred TRAIL_2ATR.
6. The current break-even rule remained best in the tested grid for MU, RCMT, HUM, SNDK, C and multiple weaker/no-trade names. Therefore the evidence favors an adaptive runner, not universal removal of break-even.
7. SNDK was the largest improvement: current v2.4 34.88% versus 84.62% using ADX >=17 and rising with the current post-3ATR break-even behavior.
8. LRCX improved from -7.05% to +14.05% with ADX >=17 and rising plus a 3ATR trailing runner.

Proposed research direction for v2.5 candidate:
- Early-trend entry sleeve: ADX >=17 AND ADX rising, with all existing bullish-trend, trend-maturity, efficiency, RSI and fresh-breakout gates preserved.
- Keep the standard stronger-trend path rather than eliminating it.
- After +3ATR harvest, classify the remaining runner:
  * STRONG_PERSISTENT: if trend remains bullish, ADX remains constructive/rising and efficiency remains strong, use a 2-3 ATR trailing runner instead of immediately reverting to average-cost break-even.
  * NORMAL/DETERIORATING: retain current break-even protection.
- Do not use NO_BE_TURTLE_TREND as the default; this grid did not support it.
- Before production, run a larger historical-universe test and hold out an out-of-sample period to avoid selecting the rule from these 16 outcomes.
