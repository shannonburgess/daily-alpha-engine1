# Turnover-Aware Entry / Hold Hysteresis Research

Status: **research only**  
Tracks: #76, #92, #105  
No paper/live authorization, sizing change, Pine/Turtle exit change, or automatic strategy promotion is introduced by this work.

## Hypothesis

Daily Alpha may improve net expectancy and institutional-scale capacity by requiring stronger evidence to **enter** or **replace** a holding than to continue holding an existing valid position.

The mechanism is a no-trade / hold buffer around the ranking boundary:

- `ENTRY_SCORE_MIN` — threshold for a fresh position;
- `HOLD_SCORE_MIN` — lower threshold for an existing position to remain in the hold region;
- `REPLACE_EDGE_MIN` — minimum point-in-time score advantage a qualified challenger needs before replacing an incumbent;
- `SOFT_PERSISTENCE_DAYS` — optional short persistence window for non-hard ranking deterioration;
- entry vs hold rank regions, e.g. top-N entry and top-(N+k) hold.

This mechanism never overrides a hard exit.

## Institutional research anchors

- Novy-Marx & Velikov, *A Taxonomy of Anomalies and their Trading Costs*, NBER Working Paper 20721, find a buy/hold spread to be an especially effective simple transaction-cost mitigation device in their anomaly portfolios.
- Frazzini, Israel & Moskowitz, *Trading Costs of Asset Pricing Anomalies*, use institutional live-trading data and show that transaction-cost-aware strategy design can materially improve net implementation and capacity.

These findings motivate a Daily Alpha test; they are not assumed to transfer directly.

## Research-only implementation

`src/daily_alpha/turnover_hysteresis.py` is deliberately disconnected from the portfolio/execution runtime. It provides an auditable classifier that can be fed point-in-time score/rank snapshots by a future backtest harness.

Actions:

- `ENTER`
- `HOLD`
- `HOLD_PERSISTENCE`
- `REPLACE`
- `EXIT_SOFT`
- `EXIT_HARD`
- `NO_ACTION`

Hard-exit precedence means Pine/Turtle exits, failed-breakout exits, earnings-risk liquidation, DATA_ERROR safety behavior, explicit thesis invalidation, and risk limits remain authoritative.

## Walk-forward test matrix

Compare at minimum:

1. baseline — current daily ranking/replacement logic;
2. score buffer only;
3. rank buffer only;
4. 1-day / 2-day / 3-day soft persistence;
5. challenger must exceed incumbent by a minimum replacement edge;
6. capacity-aware replacement edge where estimated implementation cost raises the replacement hurdle.

Do not optimize the full sample. Thresholds must be trained and evaluated through rolling or anchored out-of-sample windows.

## Segmentation

Report results by:

- market regime;
- sector/industry/theme;
- trend age/lifecycle;
- QCS/Alpha Score tier;
- normal vs earnings/catalyst setup;
- volatility state;
- dispersion/correlation state (#98);
- instrument type;
- NAV/capacity tier (#92).

## Required metrics

- gross expectancy / R;
- estimated net expectancy / R;
- one-way and round-trip turnover;
- replacement count;
- average holding period;
- estimated spread/impact cost;
- option bid/ask and roll/expiry cost when options are modeled;
- realized drawdown and left-tail behavior;
- MFE / MAE;
- percent of large winners retained;
- opportunity cost of delayed replacement;
- results excluding the best trade;
- style/ranking drift;
- capacity frontier by simulated NAV.

## No-lookahead controls

- use the ranking/score available at the actual decision timestamp;
- do not backfill future universe membership, liquidity, optionability, event dates, or factor values;
- choose hysteresis thresholds only from prior/training history;
- a held position does not gain access to any information unavailable to a new candidate;
- transaction-cost/capacity estimates must use information available at the decision time where feasible.

## Promotion rule

A challenger is not eligible for promotion merely because turnover decreases.

Promotion requires evidence that the buffer improves net expectancy/capacity or materially lowers implementation cost without:

- hiding deteriorating positions;
- weakening hard exits;
- materially worsening drawdown or tail risk;
- relying on one or two extreme winners;
- introducing unacceptable style drift;
- depending on full-sample parameter fitting.

Any later connection to portfolio construction or execution requires explicit approval and separate tests.

## Source anchors

- https://www.nber.org/papers/w20721
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498
