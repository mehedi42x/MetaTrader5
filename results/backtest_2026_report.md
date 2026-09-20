# Your rules on the 2026 data — backtest report

**Rules tested** (everything as you specified it):

| | rule |
|---|---|
| entry E1 | M1 EMA 6/9 crossover + 5m EMA 9/12 trend + Bollinger(20,2) middle filter (the pasted Pine v6 script) |
| entry E2 | M1 EMA 6/9 crossover + 5m EMA 9/12 trend (the pasted cTrader cBot) |
| exit X1 | the opposite M1 crossover (both scripts) |
| exit X2 | **your hybrid rule** - the M1 cross closes a trade only in profit; a losing trade is held until the 5m EMA 9/12 flips |
| exit X3 | the cBot trailing stop: +$2.00 trigger, $1.50 distance, +$2.00 cap |
| extra | the 09-13 UTC + EMA-separation blockers built on request earlier |

0.01 lot (1 oz), **$0.20 per round trip**, real M1 data.

## The 2026 data

| segment | window | bars | source | validated against |
|---|---|---|---|---|
| A | 2026-01-01 -> 03-11 | 67,229 | sherwynjoel/xauusd-historical-data | indirectly: intraday moves agree with segment B to $0.19/bar, LEVEL differs |
| B | 2026-03-12 -> 09-08 | 175,669 | getdata-finance/xauusd-1m-ohlcv | the real MT5 mirror: median -$0.05, mean abs $0.13 |
| C | 2026-09-09 -> 09-18 | 9,744 | real Exness MT5 mirror | it IS the reference |

Segments are never spliced: each variant is simulated inside a segment so no trade
spans a source change, and every trade is charged the full $0.20.

## Combined 2026 (Jan 1 - Sep 18)

| variant | trades | net $ | win% | PF | maxDD $ | avg hold (min) | gross $ |
|---|---|---|---|---|---|---|---|
| E1 script (MTF+BB) x cross | 8,858 | **$-1,501.59** | 27.9% | 0.93 | $-2,113.97 | 18 | $270.01 |
| E2 cBot x cross | 9,594 | **$-1,963.38** | 27.4% | 0.91 | $-2,454.08 | 18 | $-44.58 |
| E1 script x hybrid (your rule) | 4,368 | **$-443.66** | 58.7% | 0.98 | $-1,179.42 | 55 | $429.94 |
| E2 cBot x hybrid (your rule) | 4,536 | **$-565.67** | 58.6% | 0.97 | $-1,310.45 | 54 | $341.53 |
| E1 script x trail (cBot stop) | 8,858 | **$-1,367.37** | 51.4% | 0.89 | $-1,851.50 | 10 | $404.23 |
| E2 cBot x trail (cBot stop) | 9,594 | **$-1,526.91** | 50.8% | 0.89 | $-1,950.47 | 10 | $391.89 |
| E1 script x cross + blockers | 610 | **$-127.34** | 27.7% | 0.92 | $-262.95 | 12 | $-5.34 |
| E1 script x hybrid + blockers | 457 | **$-32.02** | 53.6% | 0.98 | $-351.03 | 30 | $59.38 |
| E1 script x trail + blockers | 610 | **$-6.53** | 55.2% | 0.99 | $-190.40 | 6 | $115.47 |

## Month by month 2026 (net $)

| variant | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | total |
|---|---|---|---|---|---|---|---|---|---|---|
| E1 script (MTF+BB) x cross | 324 | -626 | 269 | -439 | -477 | -315 | -232 | -117 | 112 | **-1,502** |
| E2 cBot x cross | 196 | -690 | 128 | -566 | -528 | -279 | -272 | -124 | 172 | **-1,963** |
| E1 script x hybrid (your rule) | 41 | -383 | 127 | -200 | -346 | -55 | 118 | 135 | 119 | **-444** |
| E2 cBot x hybrid (your rule) | -36 | -362 | 57 | -254 | -373 | -57 | 125 | 164 | 170 | **-566** |
| E1 script x trail (cBot stop) | 311 | -543 | 184 | -501 | -315 | -284 | -193 | -130 | 104 | **-1,367** |
| E2 cBot x trail (cBot stop) | 250 | -512 | 120 | -559 | -328 | -230 | -232 | -140 | 104 | **-1,527** |
| E1 script x cross + blockers | -63 | -42 | 41 | -95 | 9 | -27 | -29 | 5 | 75 | **-127** |
| E1 script x hybrid + blockers | -228 | -20 | 98 | -88 | -23 | 48 | 41 | 24 | 116 | **-32** |
| E1 script x trail + blockers | -31 | -13 | 42 | -56 | 11 | -48 | -30 | 52 | 65 | **-7** |

## How 2026 compares with 2022-2025

| variant | 2022-2025 (4 years) | 2026 (Jan-Sep) |
|---|---|---|
| E1 script (MTF+BB) x cross | $-11,811 | $-1,502 |
| E2 cBot x cross | $-11,865 | $-1,963 |
| E1 script x hybrid (your rule) | $-5,590 | $-444 |
| E2 cBot x hybrid (your rule) | n/a | $-566 |
| E1 script x trail (cBot stop) | $-11,781 | $-1,367 |
| E2 cBot x trail (cBot stop) | n/a | $-1,527 |
| E1 script x cross + blockers | $-613 | $-127 |
| E1 script x hybrid + blockers | n/a | $-32 |
| E1 script x trail + blockers | n/a | $-7 |

## Notes from the numbers

- E1 with the original exit: 8,858 trades in 2026, average hold 18.2 minutes, average loss $-3.15 against an average win $7.53.
- Spread paid over the nine months: $1,771.60; gross P/L $270.01.
- Your hybrid rule: 1,827 trades were held over (the M1 cross hit them under water), winning 1.3% of the time for $-19,480; the rest closed by the M1 cross in profit.
- The trailing stop closed 4,545 trades, 1,732 of them pinned at the +$2.00 cap.

Charts: results/backtest_2026.png | table: results/backtest_2026_summary.csv

## What 2026 looked like

Gold opened the year at $4,330, ripped to a high of about **$5,595** (peak in early March),
then collapsed to **$4,350** by 8 September and chopped around $4,230-4,435 into 18
September. January's range alone was **$1,286** and February's **$879** - one of the most
violent gold markets on record, and a **-22% bear leg** from the peak.

That is exactly the market the EMA 6/9 crossover is worst at: February 2026 cost the
original rule **-$626** in one month (its worst month of the year), and the whole April-August
stretch bled every month.

## Verdict

**1. 2026 repeats the verdict of 2022-2025, with the same mechanism and the same size.**

| | 2022-2025 (48 months) | 2026 (8.6 months) | per month |
|---|---|---|---|
| E1 script x cross | -$10,810.52 | -$1,501.59 | -$246 → **-$175** |
| E2 cBot x cross | -$11,864.97 | -$1,963.38 | -$247 → **-$228** |

The cost model explains it again: 8,858 trades x $0.20 = **$1,771.60** of spread, and the
gross P/L is **+$270.01** - the raw edge is zero, so the spread is the loss.

**2. Your hybrid rule (M1 cross closes only winners, losers held to the 5m flip) still does
exactly what it did in the earlier test - and still does not pay.** Win rate **58.7%** (vs
27.9%), loss cut by 70% (-$1,502 → **-$443.66**), drawdown nearly halved, but:
- 1,827 held-over trades won only **1.3%** of the time for **-$19,480**
- average win $7.53 vs average loss -$3.15 - reward/risk 2.39 against a 58.7% win rate needs
  1.7, so it is close, but the big held losses (worst -$177.14) eat the advantage
- gross P/L +$429.94 against $873.60 of spread: **the gross edge is again ~zero**

**3. The trailing stop lands in the same place** (-$1,367.37, gross +$404.23, win 51.4%,
4,545 exits by the stop of which 1,732 pinned at the +$2.00 cap).

**4. The best combination of your rules on the 2026 data is the hybrid exit with the
blockers: -$32.02 over 8.6 months (PF 0.98, win 53.6%)** - statistically flat. The
trailing-stop + blockers variant is -$6.53. Both are break-even configurations, not
profitable systems; the blockers remain an in-sample-fitted filter and must keep that label.

**5. Cross-check with the earlier real-MT5 window carried over:** the Sep 2026 segment alone
was the only strongly positive stretch for every rule (base +$27.01 on 337 trades, blockers
+$75.70, hybrid+blockers +$56.34) - nine trend-friendly days cannot overturn the eight months
around them.

**Conclusion:** on the 2026 data - a year of extreme volatility and a 22% gold bear leg - your
rules behave exactly as they did on 2022-2025: win rate and loss size move around, the gross
edge stays at zero, and the spread bill decides the result. Nothing in the 2026 data turns
any of these configurations into a profitable system. The only measured edge in this project
remains the S7 order-block retest (+$4,124.58 over 2022-2025, 4/4 positive years).
