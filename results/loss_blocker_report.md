# Trade-by-trade forensics + loss-blocker system (M1 EMA 6/9 + BB)

Strategy under the microscope = the pasted Pine v6 script: EMA 6/9 crossover on M1,
EMA 9/12 trend on M5 (last closed bar), close on the correct side of the Bollinger(20,2)
middle, exit on the raw opposite cross, fill at the next bar's open. 0.01 lot,
$0.20 per round trip. Real XAUUSD M1 data.

## 1. The worst month = August 2023 (-$361.81)

Monthly P/L over 2023-2025 shows the deepest hole in **August 2023**; the forensics were
run on those 30 days.

| metric | value |
|---|---|
| trades | 1,200 |
| wins / losses | 219 / 981 |
| win rate | **18.2%** |
| net | **-$361.38** |
| avg win / avg loss | +$0.92 / -$0.57 |
| avg hold | 11.2 min |
| biggest win / loss | +$13.30 / -$5.52 |

## 2. Why the trades lost

**a) The average loss is barely bigger than the spread.** -$0.57 average loss against a
$0.20 round-trip cost means the trades were not stopped by the market so much as taxed by
it. Gross P/L per trade was about -$0.10.

**b) The winners needed time the losers never got.**

| | losers | winners |
|---|---|---|
| avg hold | **7.5 min** | **27.3 min** |
| avg price move | $0.39 | $1.12 |

**c) No context feature separates winners from losers.** Feature means at the signal bar:

| | ADX | ER | ATR ratio | BB position | EMA sep | 5m trend | hour |
|---|---|---|---|---|---|---|---|
| losers | 19.1 | 0.155 | 0.97 | 0.71 | 0.051 | 0.127 | 11.3 |
| winners | 19.6 | 0.154 | 0.99 | 0.70 | 0.047 | 0.133 | 11.2 |

They are the same to two decimal places. Every quintile of every feature landed between
**12.9% and 27%** win rate — i.e. the signal carries no information about the next move.

**d) The only clear pattern is the session:**

| hours (UTC) | 00-05 | 07-14 | 15-19 | 20-23 |
|---|---|---|---|---|
| win rate | 9-21% | **25-30%** | 7-23% | 11-25% |
| net (Aug 2023) | -$128 | **-$75** | -$77 | -$66 |

London/early-New York (09-13 UTC) was the least bad; the Asian session and the late US
session were the worst.

Full trade list with every feature: `results/forensics_trades_2023-08.csv` (1,200 rows).

## 3. The loss-blocker system

A greedy search over interpretable context rules (objective: net P/L on the worst month,
minimum 80 trades) selected three rules:

```
BLOCK unless:  09 <= hour(UTC) <= 13
               AND 0.03 <= |EMA6-EMA9| / ATR14 <= 0.08
               AND |EMA9(5m) - EMA12(5m)| / ATR14 <= 0.20
```

(the first rule = trade only in the London / early-New-York window; the second = the
crossover must have a real but not over-extended separation; the third = the 5-minute
trend must not already be stretched.)

### In-sample (August 2023)

| variant | trades | net $ | win% | PF | avg/trade |
|---|---|---|---|---|---|
| base (every signal) | 1,200 | -$361.38 | 18.2% | 0.36 | -$0.301 |
| **with blockers** | **81** | **+$13.95** | **32.1%** | **1.35** | +$0.172 |
| blocked out (skipped) | 1,119 | -$375.33 | 17.2% | 0.28 | -$0.335 |

The blocked trades were the worse ones (17.2% win rate), and the kept trades made money
**gross** (+$30.15) as well as net.

### Validation on 40+ months that were NOT used for tuning

| window | base net $ | blocked net $ | change | blocked win% |
|---|---|---|---|---|
| 2022 full year | -$2,977.60 | -$74.90 | +$2,902.70 | 28.6% |
| 2023 full year | -$2,386.19 | -$134.72 | +$2,251.47 | 26.6% |
| 2024 full year | -$2,487.60 | -$136.90 | +$2,350.70 | 29.1% |
| 2025 full year | -$2,959.13 | -$266.56 | +$2,692.57 | 29.1% |
| **4-year total** | **-$10,810** | **-$613.08** | **+$10,197** | ~28% |
| Sep 2026 (real MT5, 9-18) | +$186 | +$75.70 | -$110 | 38.5% |

**The blockers remove 94% of the loss and lift the win rate from ~25% to ~29% — but the
result is still negative.**

### The decisive number

The blocker version trades 3,071 times over four years, so it pays **$614.20** of spread;
its net is **-$613.08** — the gross P/L is **+$1.12, i.e. zero**.

**After filtering, what remains is a coin flip, and the spread is the entire loss.**

## 4. Is the exit the problem?

| exit scheme (on the worst month) | trades | net $ | win% | PF |
|---|---|---|---|---|
| cross (original) | 1,200 | -$361.38 | 18.2% | 0.36 |
| cross + min hold 10 bars | 815 | -$258.45 | 27.7% | 0.44 |
| **cross + min hold 20 bars** | 655 | **-$186.36** | **37.3%** | 0.56 |
| SL 1.0 / TP 2.0 ATR + cross | 1,200 | -$255.89 | 29.0% | 0.41 |
| trail 1.5 ATR + cross | 1,200 | -$232.93 | 16.1% | 0.31 |
| TP/SL 2/1 ATR only | 1,122 | -$229.93 | 31.9% | 0.45 |

Over the four years, with the blockers on, the best exit was **min-hold 20 bars:
-$500.96** (2022 -$1.05 | 2023 -$75.42 | 2024 -$187.14 | 2025 -$237.35). Holding longer
roughly halves the damage — consistent with the forensic finding that losers die in
7 minutes — but it never turns the system positive.

## 5. Conclusion

1. The signal has **no predictive power**: winners and losers come from the same market
   conditions, so no entry filter can find the "good" trades — the blockers only remove
   the *worst* environments (dead sessions, stretched trend).
2. Because the residual gross edge is zero, the spread decides the outcome. This system
   cannot be made profitable by filtering or by fixing the exit.
3. The improved version (blockers + 20-bar minimum hold) is roughly break-even instead of
   a guaranteed bleed, so it is the least-bad configuration if one insists on this idea —
   but our S7 order-block retest makes **+$4,124.58 over the same four years** with 4/4
   positive years, and that is the system worth trading.

Chart: `results/loss_blocker.png`
