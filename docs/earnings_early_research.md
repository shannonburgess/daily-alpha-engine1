# Earnings Gap & Go EARLY Research

`EARNINGS_GAP_GO_EARLY` covers the canonical v2.4 **60%-<70% close-location band**. It remains research/watch-only. This branch does not authorize paper or live entries.

The canonical 70% full Gap & Go backtest baseline is now aligned on `main` through issue #70 / PR #77, so the former baseline dependency is resolved. The remaining work is empirical: run the EARLY cohort without allowing MRVL or any other single outlier to dictate the conclusion.

## Scenarios

1. `NO_ENTRY` — current production-safe behavior.
2. `STARTER_ONLY` — hypothetical 25% starter on the earnings event close.
3. `STARTER_THEN_CONFIRM` — hypothetical 25% starter, scaling to 50% only after confirmation.

Initial confirmation rules:
- T+1/T+2 close above the earnings-event high;
- T+1/T+2 close above the earnings-event close as a looser challenger.

## Historical study now unblocked

Run the 60%-<70% cohort across the broad liquid universe and historical options. Compare:
- no entry versus 25% starter versus 25%→50% confirmed scale;
- T+1 versus T+2 confirmation windows;
- event-high confirmation versus event-close confirmation;
- 45-75 DTE versus 75-120 DTE;
- a roll challenger when DTE <=14 while the underlying signal remains active.

Use only information available at the decision timestamp. Earnings date/time, event-day range, forward confirmation and option quotes must not be revised with later data.

## Required outputs

Report sample N, median/mean return, win rate, canonical R, max drawdown/MAE, MFE, tail dependence, expiry-before-exit frequency, realistic bid/ask impact, and results excluding the best trade. Show MRVL separately and also report the cohort with MRVL removed.

## Promotion gate

Do not promote an EARLY starter merely because aggregate return rises. Require stable improvement in median/expectancy and downside behavior across walk-forward/holdout slices, with enough sample size and without dependence on one or two right-tail outcomes. A null result keeps `EARNINGS_GAP_GO_EARLY` watch-only.
