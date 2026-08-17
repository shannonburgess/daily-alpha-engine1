# LRCX ADX Threshold Comparison — Mar 1 to Jul 31, 2026

Research-only. No production changes. No paper-ledger writes.

## ADX >= 17
- First entry: 2026-04-14 at 272.22
- Entry ADX: 21.214886831284623
- Additional entries: 2026-05-06 at 296.96; 2026-06-11 at 362.26
- Apr 14 trade: exit Apr 15 at 264.97, FAILED_BREAKOUT, -2.6633%
- May 6 trade: 2 adds, harvested, exit Jun 5 at 303.07, BREAK_EVEN, +0.1711%
- Jun 11 trade: 2 adds, harvested, exit Jul 2 at 351.41, BREAK_EVEN, -2.3084%
- 3 trades, 1 positive
- Aggregate return on gross deployed: -1.4320%

## ADX >= 20
- First entry: 2026-04-14 at 272.22
- Additional entries: 2026-06-02 at 334.17; 2026-06-11 at 362.26
- Apr 14 trade: -2.6633%
- Jun 2 trade: FAILED_BREAKOUT on Jun 5, -9.3066%
- Jun 11 trade: BREAK_EVEN on Jul 2, -2.3084%
- 3 trades, 0 positive
- Aggregate return on gross deployed: -4.0888%

## ADX >= 25 (current v2.4)
- First entry: 2026-06-22 at 409.54
- Second entry: 2026-06-29 at 410.91
- Jun 22 trade: FAILED_BREAKOUT Jun 23, -9.3300%
- Jun 29 trade: FAILED_BREAKOUT Jul 1, -4.7821%
- 2 trades, 0 positive
- Aggregate return on gross deployed: -7.0522%

## Interpretation
Reducing ADX from 25 to 17 moved the first eligible LRCX entry from 409.54 on Jun 22 to 272.22 on Apr 14. That is 137.32 points earlier and an entry price about 33.5% lower than the ADX-25 first entry. It materially improved this LRCX sample, but the strategy still failed to capture the full trend because FAILED_BREAKOUT and BREAK_EVEN exits repeatedly closed positions during the larger advance.

The ADX-17 threshold alone is therefore not sufficient evidence for a production change. The next test should evaluate ADX >=17 together with a rising-ADX requirement and revised early failed-breakout / post-harvest break-even behavior across a broad historical universe.
