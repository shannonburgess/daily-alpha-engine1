# Daily Alpha v2.4 Earnings Gap Backtest

Research validation for PR #69. This document is not a live-trading authorization or a performance claim.

## Period and data

- Test period: 2024-01-01 through 2026-08-14.
- Underlying history: ORATS daily OHLCV plus earnings history, with warmup data before the test window.
- Event logic: Daily Alpha v2.4 Gap & Go / Gap & Crap / Wait classification.
- Options: historical ORATS calls screened with the production option-quality rules: 45-75 DTE, bid >= $0.05, spread <= 15%, open interest >= 100, volume >= 10, and absolute delta 0.35-0.70.

## Broad 50-name underlying validation

Fixed liquid cohort across technology, semiconductors, consumer, industrials, financials, healthcare, and energy. This fixed cohort is exploratory and is not a survivorship-bias-free point-in-time production universe.

| Close-location threshold | Total trades | Cohort total R | Gap & Go trades | Gap & Go win rate | Gap & Go total R | Gap & Go avg R | Gap & Go median R | Gap R excluding best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 70% | 332 | 64.27R | 20 | 45.00% | 14.79R | 0.74R | -0.12R | 5.68R |
| 75% | 331 | 64.00R | 18 | 44.44% | 14.56R | 0.81R | -0.12R | 5.44R |

MRVL on 2026-03-06 remains `EARNINGS_WAIT` under both the 70% and 75% rules because its close location was about 62%, despite a large earnings gap, strong relative volume, and a fresh breakout.

## Historical call-option validation: midpoint marks

Focused 18-name liquid growth / semiconductor cohort. Calls were selected with the production option-quality gates and marked using historical bid/ask midpoint at entry and exit.

| Close-location threshold | Gap & Go signals | Qualified calls | No qualified option | Win rate | Average option return | Median option return | Sum of trade returns | Contracts expiring before underlying exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 70% | 10 | 9 | 1 | 55.56% | 104.98% | 9.39% | 944.82% | 2 |
| 75% | 9 | 8 | 1 | 50.00% | 105.36% | -5.22% | 842.92% | 2 |

The 70% rule adds one qualified event versus 75%: MSFT on 2026-07-30, whose historical selected call returned about +101.90% on midpoint marks through 2026-08-14.

## Historical call-option validation: conservative fills

A second run used the historical ask as entry and historical bid as exit. This intentionally assumes crossing the full spread in both directions.

| Close-location threshold | Gap & Go signals | Qualified calls | No qualified option | Win rate | Average option return | Median option return | Sum of trade returns | Contracts expiring before underlying exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 70% | 10 | 9 | 1 | 55.56% | 100.97% | 4.44% | 908.76% | 2 |
| 75% | 9 | 8 | 1 | 50.00% | 101.41% | -8.14% | 811.27% | 2 |

Qualified 70% conservative-fill outcomes included AVGO -20.73%, QCOM +420.95%, DELL +381.44%, ORCL -72.07%, MSFT +97.49%, META -84.63%, AMZN -44.47%, NFLX +226.34%, and NOW +4.44%.

## Interpretation and limitations

- The broad underlying test shows 70% and 75% produce very similar aggregate results. This is preferable to a single sharp optimum and suggests the event sleeve is not dependent on an exact cutoff.
- The option-level pilot favors 70% because its median historical call return is positive under both midpoint and conservative ask-to-bid fills, while the 75% median is negative.
- Option returns remain strongly right-tail driven. QCOM, DELL, and NFLX account for much of the positive aggregate return. Average and summed trade returns are not portfolio CAGR and should not be interpreted as such.
- The option sample is small. Only nine qualified calls were available at the 70% threshold in this focused pilot.
- Two profitable contracts expired before the underlying Turtle signal exited. A production event sleeve should therefore test a roll rule or longer initial DTE for sustained trends rather than assume one 45-75 DTE contract can always carry the complete signal.
- Commission, taxes, market impact, and intraday fill timing are not modeled. The conservative test only addresses bid/ask spread by buying at ask and selling at bid.
- The fixed cohorts are not point-in-time constituent universes, so survivorship and selection bias remain possible.

## Research conclusion

Keep Gap & Crap rejected. Keep MRVL 2026-03-06 as Wait under the validated rule rather than lowering the threshold to 60% after observing its subsequent winner. For the next paper-validation version, use a 70% minimum close location for `EARNINGS_GAP_GO`, retain the current gap-retention, relative-volume, RSI, breakout and trend requirements, and continue using the production option-quality filters. Separately test a Gap & Go option rolling / longer-DTE policy because long-running trend signals can outlive 45-75 DTE contracts.
