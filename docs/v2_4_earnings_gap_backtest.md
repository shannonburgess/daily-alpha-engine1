# Daily Alpha v2.4 Earnings Gap Backtest

Research validation for PR #69. This document is not a live-trading authorization or a performance claim.

## Period and data

- Test period: 2024-01-01 through 2026-08-14.
- Underlying history: ORATS daily OHLCV plus earnings history, with warmup data before the test window.
- Event logic: Daily Alpha v2.4 Gap & Go / Early Watch / Gap & Crap / Wait classification.
- Options: historical ORATS calls screened with the production option-quality rules: 45-75 DTE, bid >= $0.05, spread <= 15%, open interest >= 100, volume >= 10, and absolute delta 0.35-0.70.

## Broad 50-name underlying validation

Fixed liquid cohort across technology, semiconductors, consumer, industrials, financials, healthcare, and energy. This fixed cohort is exploratory and is not a survivorship-bias-free point-in-time production universe.

| Close-location threshold | Total trades | Cohort total R | Gap & Go trades | Gap & Go win rate | Gap & Go total R | Gap & Go avg R | Gap & Go median R | Gap R excluding best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 60% | 334 | 77.87R | 25 | 44.00% | 29.07R | 1.16R | -0.12R | 14.19R |
| 70% | 332 | 64.27R | 20 | 45.00% | 14.79R | 0.74R | -0.12R | 5.68R |
| 75% | 331 | 64.00R | 18 | 44.44% | 14.56R | 0.81R | -0.12R | 5.44R |

At a hypothetical 60% full-entry threshold, MRVL on 2026-03-06 becomes `EARNINGS_GAP_GO` because its close location was about 62%; the underlying test generated about +14.88R on that trade. At 70% and 75%, the same event does not qualify as a full entry. This single event explains a large portion of the 60% uplift and is why 60% is not promoted directly to an executable threshold.

## Historical call-option validation: midpoint marks

Focused 18-name liquid growth / semiconductor cohort. Calls were selected with the production option-quality gates and marked using historical bid/ask midpoint at entry and exit.

| Close-location threshold | Gap & Go signals | Qualified calls | No qualified option | Win rate | Average option return | Median option return | Sum of trade returns | Contracts expiring before underlying exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 60% | 15 | 14 | 1 | 50.00% | 140.84% | -5.22% | 1971.82% | 3 |
| 70% | 10 | 9 | 1 | 55.56% | 104.98% | 9.39% | 944.82% | 2 |
| 75% | 9 | 8 | 1 | 50.00% | 105.36% | -5.22% | 842.92% | 2 |

The 60% average is heavily influenced by a historical MRVL call that returned about +1,143.54% on midpoint marks. The 70% rule adds one qualified event versus 75%: MSFT on 2026-07-30, whose selected call returned about +101.90% on midpoint marks through 2026-08-14.

## Historical call-option validation: conservative fills

A second run used the historical ask as entry and historical bid as exit. This intentionally assumes crossing the full spread in both directions.

| Close-location threshold | Gap & Go signals | Qualified calls | No qualified option | Win rate | Average option return | Median option return | Sum of trade returns | Contracts expiring before underlying exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 60% | 15 | 14 | 1 | 50.00% | 135.73% | -8.14% | 1900.17% | 3 |
| 70% | 10 | 9 | 1 | 55.56% | 100.97% | 4.44% | 908.76% | 2 |
| 75% | 9 | 8 | 1 | 50.00% | 101.41% | -8.14% | 811.27% | 2 |

At 60%, the conservative MRVL 2026-03-06 call returned about +1,117.52%, but the median qualified-call result was -8.14%. At 70%, the median remained positive at +4.44% and the win rate was higher at 55.56%.

Qualified 70% conservative-fill outcomes included AVGO -20.73%, QCOM +420.95%, DELL +381.44%, ORCL -72.07%, MSFT +97.49%, META -84.63%, AMZN -44.47%, NFLX +226.34%, and NOW +4.44%.

## Interpretation and limitations

- The broad underlying test shows 70% and 75% produce very similar aggregate results. This is preferable to a single sharp optimum and suggests the full-entry event sleeve is not dependent on an exact cutoff.
- The option-level pilot favors 70% over both 60% and 75% on typical-trade behavior: the conservative median is positive at 70% and negative at 60%/75%, while the 70% win rate is also highest.
- The 60% threshold has substantial upside capture, but it is much more right-tail dependent. That makes the 60%-70% band worth tracking as a distinct research regime rather than promoting it directly to an automatic trade.
- Option returns remain strongly right-tail driven. Average and summed trade returns are not portfolio CAGR and should not be interpreted as such.
- The option sample is small. Only nine qualified calls were available at the 70% threshold in this focused pilot.
- Several profitable contracts expired before the underlying Turtle signal exited. A production event sleeve should therefore test a roll rule or longer initial DTE for sustained trends rather than assume one 45-75 DTE contract can always carry the complete signal.
- Commission, taxes, market impact, and intraday fill timing are not modeled. The conservative test only addresses bid/ask spread by buying at ask and selling at bid.
- The fixed cohorts are not point-in-time constituent universes, so survivorship and selection bias remain possible.

## Promoted paper-validation policy

- `EARNINGS_GAP_GO`: close location >= 70% plus the existing gap, retention, relative-volume, RSI, breakout, bullish-trend, and price requirements. This is eligible for the existing 50% starter and normal runner-add framework.
- `EARNINGS_GAP_GO_EARLY`: close location >= 60% and < 70% while otherwise meeting the same event-quality rules. This is research/watch-only in v2.4 and **does not authorize an entry**.
- `EARNINGS_GAP_CRAP`: explicit rejection / pass.
- `EARNINGS_WAIT`: ambiguous event; no entry.

The EARLY band is intentionally separated so Daily Alpha records the opportunity set without curve-fitting a 25% starter rule to MRVL after the fact. A follow-on research experiment should test the proposed 25% starter plus next-bar confirmation/scaling logic, along with longer DTE and/or systematic option rolling.
