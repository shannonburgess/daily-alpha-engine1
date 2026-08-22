# Earnings Gap & Go EARLY — Cohort Expansion Plan

Status: watch/research only. No starter or confirmation rule is promoted by this document.

## Current evidence problem
The first refreshed 2022-01-01 through 2026-07-31 screen across 61 requested liquid names produced only 14 qualifying 60%-<70% `EARNINGS_GAP_GO_EARLY` events. The 20-day mean was positive, but best-event exclusion reduced the mean materially and the 40-day distribution was right-tail unstable. The next task is therefore **sample expansion and falsification**, not threshold tuning.

## Frozen rules for expansion
Keep the current canonical definitions fixed:
- full `EARNINGS_GAP_GO`: close location >=70% plus the existing v2.4 quality gates;
- `EARNINGS_GAP_GO_EARLY`: close location >=60% and <70% plus the same core quality gates;
- EARLY remains non-executable;
- existing event-gap, retention, relative-volume, trend and RSI rules remain unchanged during cohort expansion.

Do not alter the 60/70 boundaries to increase N.

## Cohort expansion design
Build a broader point-in-time liquid U.S. equity universe with survivorship controls where feasible. At minimum:
- preserve historical symbol/date eligibility rather than relying only on today's winners;
- enforce minimum price/liquidity rules using information available at the event date;
- retain delisted/failed names when the historical data source supports them;
- exclude ETFs from the single-company earnings cohort;
- record every ticker/data failure separately from true no-event results.

Primary objective: materially increase event N across sectors and years without selecting names because their later returns are known.

## Predeclared reporting slices
Report the expanded cohort by:
- calendar year, with 2025 shown separately and never used as a repair target;
- sector;
- gap size / ATR bucket;
- close-location bucket (60-<65, 65-<70);
- relative-volume bucket;
- market-regime bucket;
- confirmation path (T+1/T+2 event-high and event-close definitions);
- MRVL included/excluded;
- best-event and top-3-event exclusion.

## Underlying-first comparison
Before options, compare using the same underlying price series:
1. NO_ENTRY baseline;
2. 25% normalized starter at the next executable session;
3. starter + scale to 50% only after the predeclared T+1/T+2 confirmation;
4. confirmation failure / cancellation path.

Measure mean/median return, win rate, normalized R, MAE/MFE, worst decile, max adverse gap, drawdown contribution, time-to-confirmation and results excluding the best event.

## Option implementation dependency
Historical option implementation remains blocked until #106/#188/#190 provide reliable distinct transport semantics and executable-side option marks. When unblocked, test 45-75 DTE and 75-120 DTE separately with:
- bid/ask-aware entry/exit assumptions;
- stale/locked/crossed quote rejection;
- expiry-before-underlying-exit;
- systematic roll cost when DTE <=14 only if the underlying signal remains active;
- liquidity/capacity constraints.

No synthetic midpoint/Black-Scholes substitute may be used as promotion evidence.

## Promotion hurdle
Do not promote an EARLY starter unless the expanded point-in-time cohort shows:
- sufficient N across multiple sectors/years;
- positive median or otherwise clearly favorable distribution after realistic costs;
- stable results after best-event/top-3 exclusion;
- no dependence on MRVL or another single event;
- confirmation policy improvement versus NO_ENTRY that survives holdout/prospective testing;
- no material worsening of portfolio drawdown/tail risk;
- option implementation evidence, if options are the proposed vehicle.

## Kill / retain-as-watch conditions
Keep EARLY watch-only or kill the starter if the apparent benefit disappears after outlier exclusion, only exists in one sector/year, requires threshold changes made after seeing outcomes, or cannot survive realistic option/execution costs.