# Daily Alpha Aug 17, 2026 Counterfactual Replay

NO LEDGER WRITES. NO LAMBDA EXECUTION. NO PAPER TRADE WAS CREATED.

## Result

The morning Top 20 was replayed against Friday, Aug. 14, 2026 using the canonical server-side v2.4 rules.

Only **RCMT** generated a Friday `ENTRY_LONG` signal. It was classified as `EARNINGS_GAP_GO`.

Friday RCMT signal context:
- Friday close / signal price: 35.05
- 20-day breakout level: 29.55
- Turtle stop / lower10: 28.05
- ATR: 1.4040386448868847
- +1 ATR no-chase ceiling for Monday: 36.45403864488688
- ADX: 37.51137297231439
- Efficiency: 0.6269165247018741
- RSI: 82.85438700607199
- Earnings gap: 11.479944674965422%
- Gap ATR: 3.9997930769062675
- Close location: 86.46%
- Gap retention: 184.64%
- Relative volume: 6.948535121561922
- 20-day average dollar volume: 1,280,987.8375

The other high-ranked names were **not Friday v2.4 entries**:
- MU: `WAIT_NO_FRESH_20D_BREAKOUT`
- LRCX: `WAIT_NO_FRESH_20D_BREAKOUT`
- FTI: `WAIT_TREND_NOT_MATURE`
- IRM: `WAIT_NO_FRESH_20D_BREAKOUT`
- PENG, RELY, SJM, PSX, VLO, WMB, OII, OGS, INVH, BATRA, HUBB, ALGN, HUM, MRK: `WAIT_NO_FRESH_20D_BREAKOUT`
- ARTNA: `DATA_ERROR` because ORATS returned zero usable daily bars

## Monday 9:45 ET revalidation

The replay attempted the ORATS historical one-minute strikes-chain endpoint for RCMT at 2026-08-17 09:45 ET. The configured ORATS account returned HTTP 403 with an explicit authorization denial, so an exact 9:45 option chain could not be reconstructed.

A second attempt to retrieve RCMT's historical 09:45 underlying minute bar from StockData also returned HTTP 403 for the configured account.

Therefore the exact 09:45 instrument/fill cannot be proven from the connected data subscriptions. Under Daily Alpha's fail-closed rules this counterfactual remains `DATA_ERROR`; it must not be counted as a trade.

RCMT would also have been **ineligible for stock fallback** because its 20-day average dollar volume was about $1.28M, well below the $50M stock-fallback minimum. Therefore a qualified/fresh option would have been required for an actual paper entry.

## Bottom line

Based on data that can be reproduced today, the system would **not have taken MU, LRCX, FTI, or IRM this morning**. The only legitimate Friday-triggered candidate was RCMT. Because the exact Monday 09:45 option data is unavailable under the current ORATS permissions, RCMT cannot be promoted from candidate to proven executed trade. Counterfactual disposition: **DATA_ERROR / NO TRADE RECORDED**.
