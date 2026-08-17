# Earnings Gap & Go EARLY Research

`EARNINGS_GAP_GO_EARLY` covers the 60%-70% close-location band discovered during v2.4 sensitivity work. It remains research/watch-only. This branch does not authorize paper or live entries.

## Scenarios

1. `NO_ENTRY` — current production-safe behavior.
2. `STARTER_ONLY` — hypothetical 25% starter on the earnings event close.
3. `STARTER_THEN_CONFIRM` — hypothetical 25% starter, scaling to 50% only after confirmation.

Initial confirmation rules:
- T+1/T+2 close above the earnings-event high;
- T+1/T+2 close above the earnings-event close as a looser challenger.

## Required historical study

Once issue #70 aligns the canonical v2.4 backtest baseline to the merged 70% rule, run the 60%-70% cohort across the broad liquid universe and historical options. Compare 45-75 DTE with 75-120 DTE and a roll policy when DTE <= 14 while the underlying signal remains active.

Report median and mean returns, win rate, R, drawdown, tail dependence, results excluding the best trade, and expiry-before-exit frequency. MRVL must be shown separately so it cannot silently drive the conclusion.
