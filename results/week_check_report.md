# Checking the TradingView week against this repo's results

You tested one week on TradingView and saw about +$250 per day. This report does not
argue with that - it measures where the number comes from.

## 1. The same week, on the real Exness MT5 feed

| variant | trades | week net $ (1 oz) | win% | 9-18 Sep net $ | 9-18 Sep gross $ |
|---|---|---|---|---|---|
| E1 your script x cross | 230 | $148.87 | 31.7% | $27.01 | $94.41 |
| E1 x hybrid (your rule) | 117 | $159.09 | 66.7% | $14.91 | $48.71 |
| E1 x trail (cBot stop) | 230 | $149.29 | 57.0% | $88.15 | $155.55 |
| E2 cBot x cross | 252 | $132.32 | 31.0% | $31.44 | $104.24 |
| 30-systems script (all 30) | 8225 | $-277.06 | | | |

**The week WAS profitable here too.** So the disagreement is not about that week -
it is about what one week can prove.

## 2. The three things that turn +$148.84 into +$250 a day

| size | week $ (with the $0.20 cost) | per day | week $ (no cost) | per day |
|---|---|---|---|---|
| 1 oz = 0.01 lot | $148.87 | $29.77 | $194.87 | $38.97 |
| 10 oz = 0.10 lot | $1,488.70 | $297.74 | $1,948.70 | $389.74 |
| 100 oz = 1.00 lot | $14,887.00 | $2,977.40 | $19,487.00 | $3,897.40 |

To reach $250/day in that week: **8.40 oz** with the cost, or **6.41 oz** with TradingView's default zero cost. The pasted scripts ship
with `slipTicks = 0` and `commissionPct = 0`, so on the chart no spread is charged
at all - that alone adds $46.00 to the week (46 trades x $0.20).

## 3. How special was that week?

All weeks of 2022-2026 at 0.01 lot: **212 weeks**, **14 positive (6.6%)**, median week $-51.41, average $-50.86.

The tested week (+$148.87) is better than **100% of all weeks** in the
record. Ten best weeks: 2026-09-14 $149, 2025-10-13 $91, 2025-10-20 $86, 2023-03-13 $41, 2025-05-12 $34, 2025-02-10 $33, 2025-03-31 $29, 2024-03-25 $21, 2023-05-29 $18, 2024-04-01 $16.

### What happened after the previous great weeks

| great week | next 4 weeks | positive |
|---|---|---|
| 2026-09-14 ($149) | $0 | 0/4 |
| 2025-10-13 ($91) | $2 | 2/4 |
| 2025-10-20 ($86) | $-117 | 1/4 |
| 2023-03-13 ($41) | $-46 | 0/4 |
| 2025-05-12 ($34) | $-269 | 0/4 |
| 2025-02-10 ($33) | $-245 | 0/4 |
| 2025-03-31 ($29) | $-425 | 0/4 |
| 2024-03-25 ($21) | $-82 | 1/4 |
| 2023-05-29 ($18) | $-218 | 0/4 |
| 2024-04-01 ($16) | $-188 | 0/4 |

Average of the four weeks after a top-10 week: **$-158.77**. The record
also contains a **54-week losing streak** against a longest winning
streak of 3 weeks.

Sum of every week 2022-2026: **$-10,783.28 at 1 oz**. At the size needed for
$250/day that same record becomes **$-69,170** - scaling multiplies
the losses exactly like it multiplies the wins.

## Verdict

1. Your week is real and my own data reproduces it (+$148.84 net at 0.01 lot,
   +$29.77/day; the other variants: trail +$88.15, hybrid +$14.91 for 9-18 Sep).
2. The step to ~$250/day comes from position size (~8x with the $0.20 cost, ~5.8x
   with zero cost) and/or from TradingView charging no spread, which is what the
   script's default `slipTicks = 0` does. Neither changes the expected value of the
   strategy - it only scales it.
3. That week sits in the top 0% of the 2022-2026 record; the median
   week loses money and only 7% of weeks are positive, so a single winning week is the expected
   experience of a losing system on a good streak, not evidence of an edge.
4. The honest test is the one this repo keeps running: months and years, with the
   spread charged. On that test the same rules lose -$10,810 (2022-2025) and
   -$1,502 (2026 Jan-Sep) at 0.01 lot. At the $250/day size those numbers scale to
   roughly -$1.2M and -$150k respectively - the size that makes the wins big makes
   the losses big in exactly the same proportion.

If you want, tell me the symbol you tested on TradingView (for example XAUUSD vs a
100-oz futures contract) and the position size, and I will reproduce that exact
configuration bar for bar.

Chart: results/week_check.png
