# S7 + S1 (M5 trend) combination test — XAUUSD 2022

Data: data/xauusd_m1_2022.csv (354,628 M1 bars). 0.01 lot, spread 20 pts = $0.20 per round trip. M5 structure mapped to M1 with no lookahead (a 5-minute bar's bias is known only at its close).

| variant | year P/L | trades | win% | PF | max DD $ | H1 | H2 | signals blocked |
|---|---|---|---|---|---|---|---|---|
| A S7 alone (baseline) | $702.06 | 1337 | 21.6% | 1.67 | $-40.04 | $408.67 | $289.81 | 0 |
| B S7 + M5 align at break | $395.51 | 730 | 22.7% | 1.68 | $-40.06 | $299.95 | $90.75 | 1128 |
| C S7 + M5 align at fill | $493.19 | 750 | 24.0% | 1.85 | $-30.39 | $311.34 | $178.27 | 819 |
| D S7 + M5 break state | $395.51 | 730 | 22.7% | 1.68 | $-40.06 | $299.95 | $90.75 | 1128 |
| E S7 + M15 align at fill | $292.52 | 723 | 22.3% | 1.49 | $-32.42 | $199.62 | $89.32 | 920 |
| F S7 from CHoCH blocks only | $-168.51 | 842 | 11.9% | 0.78 | $-210.39 | $-144.01 | $-28.32 | 0 |
| G CHoCH blocks + M5 fill | $-70.54 | 388 | 12.4% | 0.81 | $-130.63 | $-3.14 | $-71.22 | 473 |
| H S7 + fresh M5 bias (<=50 bars) | $-2.02 | 28 | 14.3% | 0.94 | $-20.22 | $-10.42 | $2.35 | 1992 |

Baseline S7: $702.06. Best variant: A S7 alone (baseline) -> $702.06 (+0.00).

Chart: results/s7_s1_combo.png

## Verdict

Filtering S7 with the M5 (S1) swing trend **does not improve total profit**:

* best filtered variant = "S7 + M5 align at fill": +$493 vs baseline +$702 for the
  year (-30% profit), with ~45% fewer trades (750 vs 1337).
* what it DOES improve: win rate 21.6% -> 24.0%, profit factor 1.67 -> 1.85, max
  drawdown -$40 -> -$30, and the two losing months (Sep/Oct) turn positive.
* filtering at the break (B/D) or with the M15 (E) is worse on every metric.
* restricting entries to order blocks created by a **CHoCH** (reversal) destroys the
  system: -$169 for the year. So the S7 edge lives in the **BOS-continuation**
  blocks, not in the reversal blocks. This is the most useful single finding here.
* requiring the M5 bias to be "fresh" (<=50 M5 bars old) removes almost all trades
  (28 left) and does not help.

If capital preservation matters more than total return, variant C is the better
trade-off; if the goal is maximum expected profit over the year, plain S7 wins.
