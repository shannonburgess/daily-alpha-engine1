# Cross-Sectional Dispersion Regime Research

Status: research challenger only. This work does not change Daily Alpha ranking, risk limits, paper execution, or live execution.

Tracks: #76 and #98.

## Hypothesis

The current trend/momentum process may behave differently when the equity cross-section shifts between orderly broad leadership, high-dispersion stock-picking conditions, and stressed high-correlation reversals. Cross-sectional return dispersion should therefore be tested as a **conditional ranking/risk diagnostic**, not assumed to be standalone alpha.

## Point-in-time design

The first implementation deliberately requires only returns known on the observation date. A daily snapshot calculates:

- median stock return;
- interquartile range (IQR);
- median absolute deviation (MAD);
- robust 90th-minus-10th percentile winner/loser spread;
- optional broad-market return.

A trailing z-score must receive only prior observations supplied by the caller. No full-sample normalization is allowed in a valid historical study.

The experimental state layer combines a trailing dispersion z-score with a separately calculated trailing average-correlation estimate. Thresholds are explicit research parameters rather than embedded trade rules.

## Proposed study

For each historical Daily Alpha decision date:

1. freeze the eligible liquid universe using point-in-time information;
2. calculate the cross-sectional snapshot after the relevant close;
3. calculate 20-day and 60-day dispersion normalization from trailing observations only;
4. estimate trailing average pairwise correlation from a stable liquid sample;
5. join the diagnostic to the candidate/rejected ledger without changing the original decision;
6. measure subsequent 1D, 5D and 20D excess returns, MFE, MAE, stop-outs and failed breakouts;
7. segment normal Turtle entries and earnings/event entries separately;
8. test challenger policies that modify only ranking confidence, maximum new positions, or theoretical risk budget;
9. report results excluding the best trade and include opportunity cost from throttled trades;
10. use walk-forward or held-out periods for any threshold evaluation.

## Promotion bar

A dispersion overlay should remain research-only unless it improves out-of-sample expectancy, drawdown or tail behavior without materially suppressing participation in sustained broad trends. Lower volatility caused only by systematically sitting in cash is not sufficient evidence.

## Source anchors

- Campbell & Lettau, *Dispersion and Volatility in Stock Returns: An Empirical Investigation*, NBER Working Paper 7144: https://www.nber.org/papers/w7144
- Daniel, Jagannathan & Kim, *Tail Risk in Momentum Strategy Returns*, NBER Working Paper 18169: https://www.nber.org/papers/w18169
- Chabot, Ghysels & Jagannathan, *Momentum Trading, Return Chasing, and Predictable Crashes*, NBER Working Paper 20660: https://www.nber.org/papers/w20660
- Stivers & Sun, *Cross-sectional Return Dispersion and Time-Variation in Value and Momentum Premiums*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1064101
- Hurst & Docherty, *Return Dispersion and Conditional Momentum Returns: International Evidence*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2720123

These papers motivate a falsifiable research test; they do not establish that the proposed Daily Alpha overlay has positive out-of-sample alpha.
