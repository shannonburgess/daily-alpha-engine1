# Daily Alpha v2.5 Large-Universe Holdout Results

Research only. No production changes, no broker calls, no Lambda execution, and no paper-ledger writes.

## Design

The preliminary v2.5 hypothesis was developed from 16 names: ALGN, C, FTI, HOOD, HUBB, HUM, IRM, JNJ, LRCX, MRK, MU, PLTR, PSX, RCMT, SNDK, and VLO. Those names were excluded from this validation.

Validation universe: 113 additional broad, liquid U.S.-traded equities across technology, financials, healthcare, industrials, energy, consumer, utilities, real estate, and materials. ORATS produced usable daily history for all 113; data errors = 0.

Reference period: 2024-01-01 through 2025-12-31.
Validation/holdout period: 2026-01-01 through 2026-07-31.

Because the v2.5 hypothesis family was influenced by a separate 2026 development sample, this is best described as a large unseen cross-sectional validation with a chronological reference period, not a perfectly untouched temporal out-of-sample experiment.

## Rules compared

1. CURRENT_V24
   - Normal entry ADX >= 25
   - Existing v2.4 breakout, bullish-trend, maturity, efficiency and RSI filters
   - Current post-3ATR average-cost break-even floor

2. EARLY17_CURRENT_BE
   - Normal entry ADX >= 17 AND ADX rising versus prior daily bar
   - All other v2.4 entry gates unchanged
   - Current post-3ATR break-even floor retained

3. CURRENT25_ADAPTIVE
   - Current ADX >= 25 entry
   - Adaptive post-3ATR runner only

4. V25_CANDIDATE
   - ADX >= 17 AND rising entry
   - After +3ATR harvest: 3ATR trail when bullish + ADX>=25/rising + efficiency>=0.35; 2ATR trail when bullish + ADX>=20 + efficiency>=0.25; otherwise current average-cost break-even protection. Runner floor can only tighten.

Earnings Gap & Go behavior was kept unchanged.

## Aggregate results

| Period | Variant | Mean symbol return | Median | Trades | Win rate | Profit factor | Positive symbols |
|---|---|---:|---:|---:|---:|---:|---:|
| 2024-25 reference | CURRENT_V24 | 0.24% | -0.32% | 522 | 26.1% | 1.06 | 51/113 |
| 2024-25 reference | EARLY17_CURRENT_BE | 0.39% | -0.13% | 728 | 26.9% | 1.29 | 52/113 |
| 2024-25 reference | CURRENT25_ADAPTIVE | 0.17% | 0.00% | 540 | 25.9% | 1.08 | 53/113 |
| 2024-25 reference | V25_CANDIDATE | 0.29% | 0.01% | 760 | 26.2% | 1.29 | 57/113 |
| 2026 validation | CURRENT_V24 | -0.62% | -0.40% | 177 | 23.7% | 0.45 | 33/113 |
| 2026 validation | EARLY17_CURRENT_BE | +0.98% | 0.00% | 236 | 31.8% | 1.22 | 52/113 |
| 2026 validation | CURRENT25_ADAPTIVE | -0.59% | -0.40% | 181 | 23.8% | 0.56 | 33/113 |
| 2026 validation | V25_CANDIDATE | +0.76% | 0.00% | 242 | 33.1% | 1.34 | 53/113 |

Gross-deployed aggregate strategy return in the 2026 validation period:
- CURRENT_V24: -1.63%
- EARLY17_CURRENT_BE: +0.50%
- CURRENT25_ADAPTIVE: -1.30%
- V25_CANDIDATE: +0.77%

These are normalized underlying-strategy backtest returns on gross deployed units, not historical option-contract returns, NAV CAGR, or a live/paper portfolio return.

## Paired cross-sectional robustness

EARLY17_CURRENT_BE minus CURRENT_V24 across the 113 symbols:
- Mean improvement: +1.60 percentage points
- Median improvement: 0.00 percentage points
- Improved / unchanged / worse: 50 / 33 / 30
- 20,000-resample bootstrap 95% CI for mean improvement: approximately +0.50pp to +3.07pp

V25_CANDIDATE minus CURRENT_V24 across the 113 symbols:
- Mean improvement: +1.37 percentage points
- Median improvement: 0.00 percentage points
- Improved / unchanged / worse: 54 / 28 / 31
- 20,000-resample bootstrap 95% CI for mean improvement: approximately +0.46pp to +2.34pp

The improvement versus current v2.4 is therefore broad enough that it is not explained solely by the original 16 development names.

## What the test says about ADX

The strongest and most stable finding is the entry rule.

Lowering the entry threshold from ADX 25 to ADX >=17 only when ADX is rising:
- Increased validation win rate from 23.7% to 31.8%
- Increased profit factor from 0.45 to 1.22
- Increased positive symbols from 33 to 52
- Flipped mean symbol return from -0.62% to +0.98%
- Flipped gross-deployed aggregate return from -1.63% to +0.50%

The adaptive runner alone, while retaining the ADX>=25 entry, did not solve the strategy. CURRENT25_ADAPTIVE remained negative in validation. This strongly suggests the late ADX entry gate is the primary structural problem.

## What the test says about the post-3ATR runner

The adaptive runner improved aggregate profit factor and gross-deployed return when combined with the early entry:
- EARLY17_CURRENT_BE: PF 1.22; gross-deployed return +0.50%
- V25_CANDIDATE: PF 1.34; gross-deployed return +0.77%

However, it lowered the simple mean symbol return from +0.98% to +0.76% because a small number of large regressions outweighed many smaller improvements.

Largest runner regressions versus EARLY17_CURRENT_BE in validation:
- AMD: +53.89% -> +11.34% (-42.55pp)
- UNH: +23.69% -> +7.85% (-15.84pp)
- TROW: +12.23% -> +1.91% (-10.31pp)
- XOM: +6.53% -> +2.62% (-3.92pp)
- MS: +3.48% -> -0.17% (-3.65pp)
- ABBV: +2.09% -> +1.11% (-0.98pp)

Examples where the adaptive runner improved the early-entry result:
- AMAT: -2.12% -> +3.69% (+5.81pp)
- QCOM: +22.73% -> +27.58% (+4.85pp)
- EMR: -1.19% -> +3.66% (+4.85pp)
- TXN: +15.70% -> +19.30% (+3.60pp)
- CSCO: +6.96% -> +10.33% (+3.37pp)
- DE: +4.63% -> +7.56% (+2.94pp)
- ELV: +6.69% -> +9.60% (+2.91pp)

Versus EARLY17_CURRENT_BE, the adaptive candidate improved 29 symbols, was unchanged on 78, and worsened 6. The six regressions were large enough that the runner should not be promoted unchanged.

## Holdout names with largest candidate improvement versus current v2.4

- QCOM: 0.00% -> +27.58% (+27.58pp)
- AMD: -9.69% -> +11.34% (+21.04pp)
- TXN: +3.57% -> +19.30% (+15.73pp)
- PWR: -2.69% -> +8.59% (+11.29pp)
- AMAT: -6.85% -> +3.69% (+10.54pp)
- EMR: -4.34% -> +3.66% (+8.00pp)
- WMB: -4.43% -> +3.54% (+7.97pp)
- TMO: -1.97% -> +5.87% (+7.84pp)
- EQIX: +2.50% -> +10.10% (+7.61pp)
- KLAC: -9.14% -> -2.04% (+7.10pp)

Largest candidate regressions versus current v2.4:
- UNH: +23.69% -> +7.85% (-15.84pp)
- XOM: +13.03% -> +2.62% (-10.42pp)
- TSLA: 0.00% -> -7.83% (-7.83pp)
- FCX: +6.35% -> -0.95% (-7.30pp)
- BKNG: 0.00% -> -6.57% (-6.57pp)
- EOG: +13.32% -> +8.23% (-5.10pp)

## Decision

The large validation supports promoting the ADX entry change to the next formal candidate:

**v2.5 Entry Candidate**
- ADX >=17 AND rising on a normal breakout
- Preserve fresh 20-day breakout
- Preserve bullish adaptive trend
- Preserve trend maturity
- Preserve efficiency >=0.20
- Preserve RSI <=80
- Preserve earnings Gap & Go sleeve unchanged

The evidence does **not** yet support replacing the current post-3ATR break-even rule with the tested adaptive runner in production. The adaptive runner remains a research sleeve until its large regressions are addressed.

Recommended next research step: keep EARLY17_CURRENT_BE as the stable benchmark and test alternative runner activation rules that only widen the runner after stronger persistence evidence, with special attention to preventing the AMD/UNH/TROW regressions. Do not modify production v2.4 until the runner test is complete and the user explicitly approves a merge/deploy.
