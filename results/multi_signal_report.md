# Multi-signal system — every strategy keeps its own signals

All strategies run inside one account: each opens its own 0.01-lot position on its own timeframe, with its own trade log and $0.20 round-trip cost. The account equity is the sum of the strategies' cumulative P/L, so several positions can be open at the same time.

Data: data/xauusd_m1_2022.csv (354,628 real M1 bars, 2022).

## 1. Each strategy alone (2022)

| strategy | TF | year P/L | trades | win% | PF | max DD $ | H1 | H2 |
|---|---|---|---|---|---|---|---|---|
| S7 order block retest | M1 | $702.06 | 1337 | 21.6% | 1.67 | $-40.02 | $403.69 | $298.37 |
| S1 swing BOS/CHoCH flip | M5 | $214.96 | 278 | 38.1% | 1.15 | $-230.56 | $246.16 | $-31.20 |
| S4 internal structure flip | M5 | $-602.46 | 1916 | 34.6% | 0.85 | $-842.41 | $-243.31 | $-359.15 |
| S6 pullback zone entry | M15 | $-288.38 | 99 | 30.3% | 0.76 | $-598.83 | $-27.19 | $-261.19 |
| EMA 9/12 reverse (reference) | M1 | $-5,446.39 | 22115 | 24.1% | 0.64 | $-5,466.93 | $-2,745.37 | $-2,701.02 |

## 2. Combinations (one account)

| combination | year P/L | trades | win% | PF | max DD $ | max DD % | H1 | H2 | max pos | avg pos |
|---|---|---|---|---|---|---|---|---|---|---|
| S7 alone | $702.06 | 1337 | 21.6% | 1.67 | $-40.02 | -0.38% | $403.69 | $298.37 | 1 | 0.35 |
| S1 alone | $214.96 | 278 | 38.1% | 1.15 | $-230.56 | -2.22% | $246.16 | $-31.20 | 1 | 1.00 |
| S4 alone | $-602.46 | 1916 | 34.6% | 0.85 | $-842.41 | -8.26% | $-243.31 | $-359.15 | 1 | 1.00 |
| S6 alone | $-288.38 | 99 | 30.3% | 0.76 | $-598.83 | -5.83% | $-27.19 | $-261.19 | 1 | 0.99 |
| EMA alone (ref) | $-5,446.39 | 22115 | 24.1% | 0.64 | $-5,466.93 | -54.59% | $-2,745.37 | $-2,701.02 | 1 | 1.00 |
| S7+S1 | $917.02 | 1615 | 24.5% | 1.37 | $-167.15 | -1.55% | $649.85 | $267.17 | 2 | 1.35 |
| S7+S1+S4 | $314.56 | 3531 | 29.9% | 1.05 | $-463.42 | -4.35% | $406.54 | $-91.98 | 3 | 2.35 |
| S7+S1+S4+S6 (4 strategies) | $26.18 | 3630 | 29.9% | 1.0 | $-923.22 | -8.47% | $379.35 | $-353.17 | 4 | 3.34 |
| ALL 5 incl. EMA | $-5,420.21 | 25745 | 24.9% | 0.76 | $-5,477.55 | -54.6% | $-2,366.02 | $-3,054.19 | 5 | 4.34 |

## 3. Month by month (multi-signal book)

| month | S7 | S1 | S4 | S6 | BOOK |
|---|---|---|---|---|---|
| Jan 2022 | $21.19 | $29.00 | $-116.91 | $50.62 | $-16.10 |
| Feb 2022 | $98.92 | $72.22 | $210.04 | $26.40 | $407.58 |
| Mar 2022 | $131.60 | $167.57 | $18.63 | $125.12 | $442.92 |
| Apr 2022 | $39.11 | $-25.16 | $-156.17 | $-69.65 | $-211.87 |
| May 2022 | $78.89 | $71.87 | $-58.69 | $-20.95 | $71.12 |
| Jun 2022 | $33.98 | $-69.34 | $-140.21 | $-138.73 | $-314.30 |
| Jul 2022 | $63.18 | $-0.79 | $-101.96 | $-4.65 | $-44.22 |
| Aug 2022 | $52.01 | $-7.90 | $-107.53 | $-145.89 | $-209.31 |
| Sep 2022 | $2.88 | $60.55 | $-95.40 | $-36.39 | $-68.36 |
| Oct 2022 | $-8.77 | $12.39 | $-83.04 | $31.15 | $-48.27 |
| Nov 2022 | $119.81 | $-152.97 | $39.77 | $-6.74 | $-0.13 |
| Dec 2022 | $69.26 | $57.52 | $-10.99 | $-98.67 | $17.12 |
| **TOTAL** | **$702.06** | **$214.96** | **$-602.46** | **$-288.38** | **$26.18** |

Profitable months for the book: **4/12**.

## 4. Daily P/L correlation

```
      S7    S1    S4    S6
S7  1.00  0.14  0.48 -0.03
S1  0.14  1.00  0.04  0.20
S4  0.48  0.04  1.00  0.05
S6 -0.03  0.20  0.05  1.00
```

Chart: results/multi_signal.png

## Verdict

**Keep S7 + S1.** On 2022 data the two-strategy book makes **+$917** (PF 1.37,
24.5% win, max drawdown -$167 = -1.55%), which is **+$215 better than S7 alone**
and still positive in both halves (+$650 H1 / +$267 H2, 7 of 12 months green).

**Adding S4 and/or S6 destroys the result** — both are standalone losers on this data
(S4 -$602, S6 -$288) and they drag the book back towards zero (+$26 with four
strategies, -$923 drawdown). They are not diversifiers, they are noise with a cost.

**Never add the EMA 9/12 reverse system** (-$5,446, DD -54.6%): with five strategies
the account loses 54%, i.e. the bad strategies completely dominate the book.

## Why S7+S1 works

Daily P/L correlation is low: S7-S1 = 0.14, S1-S6 = 0.20, S7-S6 = -0.03, S4 is the
only one moderately correlated with S7 (0.48). Because the two winners trade different
timeframes and different logic (order-block continuation vs structure flip), their bad
days rarely coincide, which is why the combined drawdown (-$167) is only 4x S7's
(-$40) while the trade count is 1,615 — and the profit adds almost linearly.

## Position sizing note

Each strategy trades its own 0.01 lot, so with 2 strategies the average exposure is
1.35 positions and the maximum is 2. Total risk scales with the number of strategies
kept: account for ~0.02 lots of XAUUSD exposure when both fire.
