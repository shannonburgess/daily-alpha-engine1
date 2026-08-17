# Daily Alpha v2.5 Runner Persistence Results

Research only. No production changes, broker calls, Lambda execution, or paper-ledger writes.

## Design

Entry was frozen at the validated v2.5 entry candidate: ADX >=17 AND rising, while preserving the existing fresh 20-day breakout, bullish adaptive trend, trend maturity, efficiency >=0.20, RSI <=80, and unchanged earnings Gap & Go behavior.

Universe: 113 additional broad liquid U.S.-traded equities; the 16 development names (ALGN, C, FTI, HOOD, HUBB, HUM, IRM, JNJ, LRCX, MRK, MU, PLTR, PSX, RCMT, SNDK, VLO) remained excluded.

Runner-selection/reference period: 2022-01-01 through 2022-12-31.
Untouched runner holdout: 2023-01-01 through 2023-12-31.
ORATS usable histories: 113/113; data errors = 0.

Runner variants tested after +3ATR harvest:
- BENCHMARK_BE: current average-cost break-even floor.
- STRONG_BE_MINUS_1ATR: while persistence remains strong, relax floor to average cost minus 1 ATR; immediately re-arm BE when strength weakens.
- STRONG_BE_MINUS_2ATR: same concept at minus 2 ATR.
- STRONG_TRAIL4_CAPPED_BE: strong-trend 4ATR trail capped so it never tightens above break-even; otherwise BE.
- STRONG_GRACE3: up to three bars with no BE while persistence remains strong; then BE.
- STRONG_UNTIL_WEAK: no BE while persistence is strong; immediately re-arm BE when strength weakens.

Persistence required bullish adaptive trend, ADX >=20, efficiency >=0.25, and ADX not deteriorating by more than 0.75 versus the prior bar.

## Aggregate results

All six runner variants produced identical aggregate results in both periods.

### 2022 selection/reference
- Mean symbol return: -1.52%
- Median symbol return: -1.25%
- Gross-deployed return: -1.16%
- Trades: 300
- Win rate: 20.7%
- Profit factor: 0.48
- Positive symbols: 33/113
- Rule selected from 2022 by the pre-declared ranking method: BENCHMARK_BE

### 2023 untouched holdout
- Mean symbol return: +1.59%
- Median symbol return: +0.89%
- Gross-deployed return: +1.62%
- Trades: 365
- Win rate: 33.4%
- Profit factor: 2.20
- Positive symbols: 61/113

Every alternative runner had a paired mean delta of 0.00 percentage points versus BENCHMARK_BE in 2023: improved / unchanged / worse = 0 / 113 / 0.

## Why the runner variants were identical

The post-3ATR floor was not the dominant exit mechanism.

### 2022 benchmark exit paths
- Total trades: 300
- Trades reaching +3ATR harvest: 62
- FAILED_BREAKOUT exits: 136
- TURTLE_10 exits: 130
- BREAK_EVEN exits: 17
- MARK_TO_END: 11
- TREND_FLIP exits: 6
- Adds: 174 trades had 0 adds, 35 had 1 add, 91 had 2 adds.

### 2023 benchmark exit paths
- Total trades: 365
- Trades reaching +3ATR harvest: 109
- FAILED_BREAKOUT exits: 141
- TURTLE_10 exits: 136
- BREAK_EVEN exits: 16
- MARK_TO_END: 64
- TREND_FLIP exits: 8
- Adds: 182 trades had 0 adds, 35 had 1 add, 148 had 2 adds.

Although the alternative floors temporarily relaxed break-even during strong persistence, prices did not cross the relaxed floor in a way that changed the final exit before persistence weakened and BE was re-armed. Therefore the variants converged to the same realized outcomes.

## Decision

Do not change the post-3ATR runner based on the LRCX-specific result. The wider-runner benefit seen in a few 2026 development names did not generalize in this fresh 113-stock 2022/2023 study.

The robust v2.5 candidate remains:
- ADX >=17 AND rising for normal breakout entry.
- Preserve all other v2.4 entry gates and earnings Gap & Go behavior.
- Preserve the existing +1ATR / +2ATR add logic.
- Preserve +3ATR harvest.
- Preserve current post-harvest average-cost break-even runner protection.

If additional exit research is pursued, the evidence says the higher-value targets are FAILED_BREAKOUT and TURTLE_10 behavior, not the post-3ATR break-even floor. Any change to those earlier exits should be tested separately and must not be inferred from the LRCX case alone.
