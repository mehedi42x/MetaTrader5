# XAUUSD — LuxAlgo Smart Money Concepts (SMC) backtest

> If you use this port, credit the original: **"Smart Money Concepts [LuxAlgo]"**
> by LuxAlgo, Pine v5, licensed **CC BY-NC-SA 4.0** (non-commercial). Only the
> decision logic was ported to Python; the drawing code is not reproduced.

Ported from the Pine v5 indicator “Smart Money Concepts [LuxAlgo]” (CC BY-NC-SA 4.0): swing structure (size 50), internal structure (size 5), BOS/CHoCH, premium/discount equilibrium, FVG, order blocks — all on closed bars, entry at the next bar open.

Sizing: 0.01 lot (1 oz), cost $0.20/trade (spread 20 pts), leverage 1:1000.

## Results per system (0.01 lot)

### M1

| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |
|---|---|---|---|---|---|---|
| S1 swing bias flip | $102.35 | 98 | 1.47 | $-14.28 | 222 | 0.97 |
| S2 CHoCH only | $103.97 | 97 | 1.48 | $-16.53 | 221 | 0.97 |
| S3 BOS entry / CHoCH exit | $-11.15 | 60 | 0.94 | $47.40 | 124 | 1.18 |
| S4 internal bias flip | $-147.76 | 821 | 0.83 | $-426.06 | 1666 | 0.73 |
| S5 internal CHoCH only | $-147.76 | 821 | 0.83 | $-428.68 | 1665 | 0.73 |
| S6 pullback zone entry | $102.35 | 98 | 1.47 | $-14.28 | 222 | 0.97 |
| S7 order block retest | $124.78 | 104 | 2.52 | $138.58 | 236 | 1.8 |

### M5

| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |
|---|---|---|---|---|---|---|
| S1 swing bias flip | $139.39 | 20 | 3.12 | $160.96 | 44 | 1.89 |
| S2 CHoCH only | $139.39 | 20 | 3.12 | $148.86 | 43 | 1.82 |
| S3 BOS entry / CHoCH exit | $75.60 | 14 | 1.98 | $81.55 | 23 | 1.64 |
| S4 internal bias flip | $221.57 | 144 | 1.9 | $108.20 | 330 | 1.19 |
| S5 internal CHoCH only | $223.20 | 143 | 1.91 | $84.88 | 329 | 1.15 |
| S6 pullback zone entry | $139.39 | 20 | 3.12 | $160.96 | 44 | 1.89 |
| S7 order block retest | $78.84 | 21 | 2.46 | $47.25 | 46 | 1.45 |

### M15

| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |
|---|---|---|---|---|---|---|
| S1 swing bias flip | $9.36 | 8 | 1.09 | $53.50 | 15 | 1.43 |
| S2 CHoCH only | $9.36 | 8 | 1.09 | $60.46 | 14 | 1.51 |
| S3 BOS entry / CHoCH exit | $67.20 | 8 | 5.31 | $5.43 | 13 | 1.06 |
| S4 internal bias flip | $115.49 | 47 | 1.72 | $24.00 | 112 | 1.06 |
| S5 internal CHoCH only | $115.49 | 47 | 1.72 | $41.64 | 111 | 1.11 |
| S6 pullback zone entry | $96.36 | 6 | 3.35 | $140.50 | 13 | 3.2 |
| S7 order block retest | $8.54 | 11 | 1.23 | $2.17 | 18 | 1.04 |


## Best systems (2-month totals, 0.01 lot)

| rank | system | best TF | 2-month P/L | trades | win% | avg win | avg loss | exp/trade |
|---|---|---|---|---|---|---|---|---|
| 1 | S7 order block retest | M1 | **+$263.36** | 340 | 19.7% | $7.73 | -$0.93 | +$0.77 |
| 2 | S1/S2 swing bias (BOS/CHoCH) | M5 | **+$300.35 / +$288.25** | 64 | — | — | — | — |
| 3 | S4/S5 internal structure | M5 | **+$329.77** | 474 | — | — | — | — |
| 4 | S6 pullback zone entry | M15 | **+$236.86** | ~19 | — | — | — | — |

Trade quality (M1, both months): S7 wins only 19.7% of the time but its average win
is $7.73 against an average loss of $0.93 — the classic order-block retest profile
(small stop, larger runner). S1 has 33.8% wins with avg win $7.57 / avg loss $3.44.

## Robustness (parameter sensitivity, 2-month totals)

| internal / swing size | S4 M5 | S7 M1 | S1 M1 | S1 M5 |
|---|---|---|---|---|
| 5 / 50 (defaults) | +$329.77 | +$263.36 | +$88.07 | +$300.35 |
| 5 / 34 | +$331.75 | +$480.48 | +$80.95 | +$234.61 |
| 3 / 50 | +$8.50 | +$263.36 | +$88.07 | +$300.35 |
| 7 / 50 | +$25.66 | +$263.36 | +$88.07 | +$300.35 |
| 5 / 20 | +$283.73 | +$386.76 | +$42.37 | +$166.52 |

S7 stays positive in every setting; S4 is very sensitive to the internal size
(5 works, 3 and 7 collapse). Treat S4 as curve-fit, S7 as the more trustworthy one.

## Lookahead check

The structure function was re-computed on truncated data and compared bar by bar:
truncation mismatches = 0 (bias/event/tag identical). Signals are taken from a
closed bar and filled at the next bar's open, so the backtest is causal.

## Caveats

* One month (Feb-2022) plus one validation month (Jan-2022), one instrument (XAUUSD),
  20,849 M1 bars — a small sample for a strategy with ~100 trades.
* Spread fixed at 20 points; gold spread widens at news/rollover, and the S7 setup
  trades rarely, so per-trade slippage matters more than the average suggests.
* No MT5 EA exists yet for these rules.
