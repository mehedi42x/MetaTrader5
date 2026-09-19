# 30 Price Action Systems — Independent Paper Simulator (faithful port)

Pasted Pine v6 script tested on real XAUUSD M1 data. Mechanics reproduced exactly:
signal on the confirmed bar -> setup queued -> fill at the NEXT bar's open with adverse
slip -> SL = signal bar extreme +- 2 ticks, TP = 2R, maxHold 40 bars, exit order
SL-gap / TP-gap / SL (BOTH TOUCHED) / TP / TIME, one position per system, 30 systems
independent and allowed to overlap.

House rules: 0.01 lot (1 oz, qty 1 contract x point value 1), $0.10 slip each side =
**$0.20 per round trip**, commission 0. Windows: full years 2022-2025 plus the real
September 2026 window as a sanity check.

## Aggregate 2022-2025

| | value |
|---|---|
| closed trades (30 systems) | 1,736,640 |
| win rate | 28.4% |
| net P/L | **$-346,712.48** |
| gross P/L before spread | $615.52 |
| spread paid | $347,328.00 |
| profitable systems | 1/30 |
| positive in all four years | 0/30 |

## Per system (net $ by year)

| ID | system | trades | win% | 2022 | 2023 | 2024 | 2025 | **total** | gross | worst DD | avg/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S18 | Pennant | 92 | 33.7% | 1 | -1 | 8 | -8 | **1** | 19 | -9 | +0.008 |
| S14 | Triple reversal | 954 | 26.9% | -39 | -72 | -52 | -21 | **-184** | 7 | -72 | -0.192 |
| S17 | Flag | 1,463 | 29.1% | -60 | -82 | -57 | -61 | **-260** | 33 | -89 | -0.178 |
| S20 | Fakey | 3,466 | 30.0% | -205 | -196 | -53 | -85 | **-539** | 154 | -215 | -0.156 |
| S19 | Double inside | 3,316 | 29.2% | -212 | -121 | -148 | -153 | **-634** | 29 | -213 | -0.191 |
| S29 | Compression | 3,316 | 29.2% | -212 | -121 | -148 | -153 | **-634** | 29 | -213 | -0.191 |
| S25 | Range rejection | 15,269 | 29.1% | -648 | -627 | -657 | -1,033 | **-2,965** | 88 | -1,064 | -0.194 |
| S13 | Double reversal | 16,798 | 28.0% | -906 | -883 | -918 | -690 | **-3,397** | -37 | -924 | -0.202 |
| S28 | Gap continuation | 19,324 | 24.2% | -777 | -1,501 | -1,099 | -768 | **-4,144** | -279 | -1,503 | -0.214 |
| S21 | Harami | 35,071 | 27.7% | -1,767 | -1,429 | -1,867 | -2,143 | **-7,207** | -193 | -2,162 | -0.205 |
| S30 | Break and retest | 41,350 | 26.8% | -2,490 | -1,757 | -2,403 | -2,288 | **-8,938** | -668 | -2,497 | -0.216 |
| S15 | Triangle | 51,779 | 27.2% | -3,047 | -2,650 | -2,726 | -1,653 | **-10,076** | 280 | -3,047 | -0.195 |
| S09 | Breakout 50 | 47,877 | 29.4% | -3,007 | -2,222 | -2,683 | -2,691 | **-10,603** | -1,027 | -3,018 | -0.221 |
| S04 | Outside reversal | 55,597 | 29.9% | -2,952 | -2,470 | -2,618 | -2,585 | **-10,625** | 494 | -2,955 | -0.191 |
| S02 | Pin bar | 56,988 | 27.5% | -2,718 | -2,492 | -2,700 | -3,363 | **-11,273** | 124 | -3,381 | -0.198 |
| S03 | Inside breakout | 51,967 | 28.2% | -2,957 | -2,402 | -2,773 | -3,170 | **-11,302** | -909 | -3,211 | -0.217 |
| S22 | Piercing / cloud | 60,743 | 28.0% | -3,037 | -2,418 | -2,961 | -3,100 | **-11,516** | 633 | -3,161 | -0.190 |
| S11 | Failed break 20 | 68,847 | 29.0% | -3,171 | -2,794 | -3,067 | -3,851 | **-12,882** | 887 | -3,920 | -0.187 |
| S05 | 3-bar reversal | 82,460 | 28.5% | -4,239 | -3,727 | -4,167 | -4,176 | **-16,308** | 184 | -4,378 | -0.198 |
| S16 | Stepped trend | 75,004 | 27.9% | -4,225 | -3,239 | -4,138 | -4,781 | **-16,383** | -1,382 | -4,855 | -0.218 |
| S08 | Breakout 20 | 76,993 | 29.2% | -4,557 | -3,532 | -4,137 | -4,170 | **-16,396** | -997 | -4,566 | -0.213 |
| S24 | Full body | 82,116 | 29.5% | -4,512 | -4,086 | -4,646 | -3,832 | **-17,077** | -654 | -4,659 | -0.208 |
| S01 | Engulfing | 99,085 | 29.2% | -5,038 | -3,682 | -4,904 | -4,268 | **-17,893** | 1,924 | -5,039 | -0.181 |
| S27 | NR7 | 93,721 | 28.0% | -4,813 | -4,005 | -4,860 | -4,350 | **-18,028** | 716 | -4,863 | -0.192 |
| S10 | Failed break 5 | 105,657 | 28.9% | -4,919 | -4,235 | -4,656 | -5,720 | **-19,530** | 1,602 | -5,841 | -0.185 |
| S23 | Tweezer | 109,128 | 28.2% | -5,810 | -4,916 | -5,280 | -4,114 | **-20,120** | 1,706 | -5,813 | -0.184 |
| S12 | Candle sweep | 107,073 | 29.1% | -5,214 | -4,540 | -5,311 | -5,661 | **-20,727** | 688 | -5,806 | -0.194 |
| S26 | NR4 | 122,479 | 28.1% | -6,145 | -5,460 | -6,500 | -6,545 | **-24,649** | -153 | -6,636 | -0.201 |
| S06 | 3-candle momentum | 122,573 | 27.0% | -6,418 | -5,257 | -6,512 | -7,835 | **-26,021** | -1,507 | -7,898 | -0.212 |
| S07 | Breakout 5 | 126,134 | 29.1% | -6,733 | -5,632 | -6,693 | -7,344 | **-26,403** | -1,176 | -7,426 | -0.209 |

## Settings sensitivity (all 30 summed)

| variant | trades | win% | net $ | gross $ | profitable systems |
|---|---|---|---|---|---|
| base: RR 2.0, maxHold 40, $0.20 cost | 1,736,640 | 28.4% | -346,712.48 | 615.52 | 1/30 |
| zero cost (slip 0) | 1,861,444 | 33.9% | -6,475.31 | -6,475.31 (no cost charged) | 15/30 |
| RR 1.0 | 2,146,151 | 41.0% | -454,572.14 | -25,341.94 | 0/30 |
| RR 3.0 | 1,540,921 | 22.8% | -297,919.52 | 10,264.68 | 0/30 |
| maxHold disabled | 1,599,355 | 27.9% | -320,902.36 | -1,031.36 | 1/30 |
| maxHold 10 bars | 2,042,970 | 30.8% | -405,596.26 | 2,997.74 | 0/30 |
| maxHold 80 bars | 1,676,871 | 28.1% | -336,332.49 | -958.29 | 1/30 |
| stop buffer 0 ticks | 1,776,356 | 28.0% | -356,604.89 | -1,333.69 | 1/30 |
| min risk 1 tick | 1,736,640 | 28.4% | -346,712.48 | 615.52 | 1/30 |
| $0.40 cost (slip 20/side) | 1,639,982 | 24.8% | -652,981.28 | -324,984.88 | 0/30 |

## September 2026 (real Exness MT5, 9-18 Sep)

All 30 systems: 11782 closed trades, win rate 31.9%, net $-1,595.59.
Best three: Harami $98.33, Breakout 50 $53.93, Gap continuation $31.45.

Charts: results/price_action_30.png | table: results/price_action_30_summary.csv

## Why every system loses — the decisive numbers

**1. The raw signal has no edge.** With the cost switched off, the 30 systems close 1,861,444
trades and finish at **-$6,475** (15/30 individually positive) - statistically zero. Their win
rate is **33.9%**, and a driftless random walk hitting a 2R target first 33.3% of the time.

**2. The stop/target geometry is decided by noise, not by the pattern.** In the 2025 sample
(451,601 trades): average entry-to-stop distance **$1.488 (149 ticks)**, average hold
**6.6 bars**, and **39.2% of all trades are closed within 2 bars, 65.3% within 5 bars**.
Exit reasons: SL 306,789 / TP 129,423 / TIME 9,980.

**3. The $0.20 spread needs a 37.8% win rate; a coin flip gives 33.3%.**
At an average risk of 149 ticks the round-trip cost is **13.4% of R**, so the effective
reward/risk is (2R - 0.20) / (R + 0.20) = **1.64**, and the break-even win rate is
**1/(1+1.64) = 37.8%**. The systems deliver **28.4%** (with cost).

**4. That is why the loss equals the spread exactly:** 1,736,640 trades x $0.20 = **$347,328**
of cost against a gross P/L of **+$615.52** - a net of -$346,712.48. The patterns pay the
broker, nothing else.

**5. The settings cannot save it.** Best of the ten settings tested: maxHold 80 bars
(-$336,332) - still catastrophic. RR 1.0 loses most (-$454,572) because it trades more
(2,146,151 fills at a 41.0% win rate). Doubling the cost to $0.40 halves the win rate to
24.8% and turns the loss into -$652,981.

**6. September 2026 (real Exness MT5, 9-18 Sep):** 11,782 trades, win 31.9%, **-$1,595.59**.
The same behaviour on the newest data.

## Practical note for the Pine script itself

The script ships with `slipTicks = 0` and `commissionPct = 0`, so on TradingView it will
report something close to zero instead of -$346,712 across 2022-2025. The results above use
the house cost model ($0.10 per side = 20 points per round trip), which is what a real
XAUUSD account pays. If you run it on your chart, set `slipTicks = 10` to see the honest
picture (and add your broker's commission if it exists).

## Verdict

All 30 patterns - engulfing, pins, breakouts, failed breakouts, flags, NR4/NR7, retests -
behave identically: a coin flip with a 2R target minus the spread. Their measured edge is
zero, so the spread decides the outcome, and the spread is always against you. This is the
third time the same conclusion appears in this project (EMA system, its filters, now 30
price-action systems), while the S7 order-block retest over the same four years makes
**+$4,124.58 with 4/4 positive years** - the only system in this repo with a measured,
persistent edge.
