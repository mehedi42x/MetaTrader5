# XAUUSD — LuxAlgo Smart Money Concepts (SMC) backtest

Ported from the Pine v5 indicator “Smart Money Concepts [LuxAlgo]” (CC BY-NC-SA 4.0): swing structure (size 50), internal structure (size 5), BOS/CHoCH, premium/discount equilibrium, FVG, order blocks — all on closed bars, entry at the next bar open.

Sizing: 0.01 lot (1 oz), cost $0.20/trade (spread 20 pts), leverage 1:1000.

## Results per system (0.01 lot)

### M1

| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |
|---|---|---|---|---|---|---|
| S1 swing bias flip | $102.35 | 98 | 1.47 | $-77.88 | 110 | 0.68 |
| S2 CHoCH only | $103.97 | 97 | 1.48 | $-80.13 | 109 | 0.68 |
| S3 BOS entry / CHoCH exit | $-11.15 | 60 | 0.94 | $48.53 | 59 | 1.68 |
| S4 internal bias flip | $-147.76 | 821 | 0.83 | $-238.00 | 784 | 0.65 |
| S5 internal CHoCH only | $-147.76 | 821 | 0.83 | $-240.62 | 783 | 0.65 |
| S6 pullback zone entry | $102.35 | 98 | 1.47 | $-77.88 | 110 | 0.68 |
| S7 order block retest | $124.78 | 104 | 2.52 | $21.19 | 118 | 1.27 |

### M5

| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |
|---|---|---|---|---|---|---|
| S1 swing bias flip | $139.39 | 20 | 3.12 | $25.52 | 21 | 1.23 |
| S2 CHoCH only | $139.39 | 20 | 3.12 | $13.42 | 20 | 1.12 |
| S3 BOS entry / CHoCH exit | $75.60 | 14 | 1.98 | $5.95 | 9 | 1.12 |
| S4 internal bias flip | $221.57 | 144 | 1.9 | $-115.99 | 174 | 0.63 |
| S5 internal CHoCH only | $223.20 | 143 | 1.91 | $-139.31 | 173 | 0.56 |
| S6 pullback zone entry | $139.39 | 20 | 3.12 | $25.52 | 21 | 1.23 |
| S7 order block retest | $78.84 | 21 | 2.46 | $-30.69 | 24 | 0.4 |

### M15

| system | Feb P/L | Feb trd | Feb PF | Jan P/L | Jan trd | Jan PF |
|---|---|---|---|---|---|---|
| S1 swing bias flip | $9.36 | 8 | 1.09 | $52.15 | 7 | 4.18 |
| S2 CHoCH only | $9.36 | 8 | 1.09 | $59.11 | 6 | 7.26 |
| S3 BOS entry / CHoCH exit | $67.20 | 8 | 5.31 | $-63.44 | 4 | 0.09 |
| S4 internal bias flip | $115.49 | 47 | 1.72 | $-78.53 | 59 | 0.62 |
| S5 internal CHoCH only | $115.49 | 47 | 1.72 | $-60.89 | 58 | 0.68 |
| S6 pullback zone entry | $96.36 | 6 | 3.35 | $52.15 | 7 | 4.18 |
| S7 order block retest | $8.54 | 11 | 1.23 | $-0.84 | 6 | 0.88 |

