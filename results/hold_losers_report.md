# Hybrid exit: M1 cross closes only winners, losers are held for the 5m flip

Rule as asked: a trade in PROFIT is closed by the M1 EMA 6/9 reverse cross; a trade in LOSS is not closed by that cross and is held until the 5m EMA 9/12 trend flips against the position. 0.01 lot, $0.20/trade.

## Worst month (August 2023)

| variant | trades | net $ | win% | PF | maxDD $ | avg hold (min) | worst trade $ |
|---|---|---|---|---|---|---|---|
| original | 1200 | $-361.38 | 18.2% | 0.36 | $-362.59 | 11 | $-5.52 |
| hybrid (5m flip closes all) | 509 | $-144.40 | 51.3% | 0.61 | $-151.44 | 48 | $-8.33 |
| hybrid (5m flip closes losers only) | 509 | $-145.07 | 51.3% | 0.61 | $-152.11 | 48 | $-8.33 |
| hybrid + hard stop 2.5 ATR | 713 | $-216.05 | 38.0% | 0.51 | $-218.43 | 29 | $-3.53 |

## Four full years 2022-2025

| variant | 2022 | 2023 | 2024 | 2025 | total | trades | win% | maxDD $ |
|---|---|---|---|---|---|---|---|---|
| base (original exit) | $-2,978 | $-2,386 | $-2,488 | $-2,959 | **$-10,811** | 48082 | 24.0% | $-10,842 |
| hybrid: 5m flip closes all | $-1,464 | $-1,174 | $-1,138 | $-1,814 | **$-5,590** | 22440 | 54.8% | $-5,651 |
| hybrid: 5m flip closes losers | $-1,462 | $-1,167 | $-1,141 | $-1,833 | **$-5,603** | 22438 | 54.7% | $-5,664 |
| hybrid + hard stop 2.5 ATR | $-1,783 | $-1,189 | $-1,465 | $-1,799 | **$-6,236** | 30248 | 42.7% | $-6,264 |
| hybrid + hard stop 4 ATR | $-1,499 | $-989 | $-1,193 | $-1,715 | **$-5,396** | 24937 | 50.7% | $-5,457 |
| hybrid + min hold 5 bars | $-1,457 | $-1,174 | $-1,128 | $-1,804 | **$-5,562** | 22426 | 54.9% | $-5,624 |

With the entry blockers (09-13 UTC + EMA separation window) on:

| variant | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|
| base (original exit) | $-75 | $-135 | $-137 | $-267 | **$-613** |
| hybrid: 5m flip closes all | $13 | $-73 | $-101 | $-103 | **$-264** |
| hybrid: 5m flip closes losers | $11 | $-73 | $-106 | $-105 | **$-273** |
| hybrid + hard stop 2.5 ATR | $-4 | $-45 | $-65 | $-157 | **$-271** |
| hybrid + hard stop 4 ATR | $13 | $-44 | $-70 | $-103 | **$-205** |
| hybrid + min hold 5 bars | $15 | $-74 | $-96 | $-94 | **$-249** |

Charts: results/hold_losers.png

Trades closed by the 5m flip: 10091 of 22440 over four years; their win rate 0.7%; worst single trade $-52.53; longest hold 75.7 hours.

## Verdict — the rule works exactly as designed, and it still cannot make this system profitable

**What the rule achieves (2022-2025, no entry blockers, 0.01 lot, $0.20/trade):**

| | original (M1 cross closes all) | hybrid (M1 cross closes only winners, losers held to the 5m flip) |
|---|---|---|
| trades | 48,082 | 22,440 |
| win rate | 24.0% | **54.8%** |
| average win | $2.25 | $2.20 |
| average loss | **-$1.01** | **-$3.23** |
| 4-year net | **-$10,810.52** | **-$5,590.22** |
| spread paid | $9,616 | $4,488 |
| max drawdown | -$10,841 (account wiped) | -$5,651 |
| gross P/L before spread | -$1,194 | -$1,102 |

The win rate doubles, the trade count halves (so the spread bill halves), the drawdown halves
and the account is no longer wiped out. That is a real improvement in every risk metric.

**Why it is still a loss:** the exit change moves money from the loss column to... the loss
column, just in bigger pieces.

| | winners | losers |
|---|---|---|
| average hold (original) | 39 min | 11 min |
| average hold (hybrid) | 63 min | **58 min** |

* The 10,091 trades that were held over (because the M1 cross hit them while they were
  under water) have a win rate of **0.7%** and average **-$3.23** each: they contribute
  **-$32,634** of the four-year loss.
* The winners never got bigger: average win stayed at $2.20. So the reward/risk went from
  2.2:1 to 0.68:1 while the win rate went from 24% to 55% - and at 55% you need better
  than 0.82:1 to break even, so it is still short.
* The rule also creates tail risk: the longest hold is **75.7 hours** and the single worst
  trade is **-$52.53** (five days of average profit in one trade), versus 11-minute,
  -$1.01 losses before.

**The decisive number is the same as in the forensics report:** gross P/L over four years is
**-$1,194 (original)** versus **-$1,102 (hybrid)** - statistically the same. The exit rule
changes *when* and *in how many pieces* the money is lost; it does not create an edge,
because the entry signal has none.

**Best configuration found:** hybrid exit + entry blockers (09-13 UTC, EMA separation
0.03-0.08) + a 4-ATR disaster stop = **-$204.67 over four years** (2022 +$12.60 |
2023 -$44.07 | 2024 -$70.20 | 2025 -$103.00), i.e. roughly break-even territory and a
**+$10,600 improvement over the original** - but still not a profitable system.

For comparison, S7 order-block retest on the same four years: **+$4,124.58**, 4/4 positive.
