# XAUUSD 2022 — LuxAlgo “Universal Signal Backtester” port

Ported from the Pine v6 indicator (CC BY-NC-SA 4.0, (c) LuxAlgo): predefined 9/21 EMA cross by default, ATR(14)-based TP1/2/3 (partial exits of 1/3 each) and SL 1.5/2.5/3.5 (nearest touched stop closes the whole remainder, checked before the TPs each bar), reversal on the opposite signal, entry at the signal bar's close.

Data: data/xauusd_m1_2022.csv (354,628 real M1 bars). Size 0.01 lot (1 oz), cost $0.20 per round trip (spread 20 points, charged pro-rata on partial exits).

## Presets x timeframes (default TP/SL)

| preset | M1 | M5 | M15 | H1 |
|---|---|---|---|---|
| 9/21 EMA (default) | $-3,703.66 (16720 trd, PF 0.55) | $-866.11 (3339 trd, PF 0.74) | $-239.52 (1048 trd, PF 0.85) | $68.48 (263 trd, PF 1.09) |
| 12/26 EMA | $-2,822.64 (12993 trd, PF 0.56) | $-651.54 (2589 trd, PF 0.75) | $-222.09 (844 trd, PF 0.84) | $12.87 (201 trd, PF 1.02) |
| 50/200 SMA (golden/death) | $-424.94 (2309 trd, PF 0.63) | $-129.37 (453 trd, PF 0.75) | $-12.38 (142 trd, PF 0.95) | $8.47 (30 trd, PF 1.08) |

## TP/SL variants (9/21 EMA)

| variant | M1 | M5 | M15 | H1 |
|---|---|---|---|---|
| default TP1/2/3 + SL1.5 | $-3,703.66 | $-866.11 | $-239.52 | $68.48 |
| stop only (SL 1.5, rev exit) | $-3,825.05 | $-934.34 | $-257.32 | $187.01 |
| TPs only (no stop) | $-4,107.13 | $-872.07 | $-238.98 | $80.43 |
| single TP 2.0 + SL 1.5 | $-3,603.28 | $-881.52 | $-242.63 | $48.39 |
| wide: TP 2/4/6 + SL 2.0 | $-3,862.27 | $-879.52 | $-193.49 | $227.02 |
| tight: TP 0.5/1/1.5 + SL 1.0 | $-3,732.94 | $-908.76 | $-159.39 | $-31.11 |

## ATR choppiness filter (9/21 EMA)

| filter | M1 | M5 | M15 | H1 |
|---|---|---|---|---|
| OFF | $-3,703.66 | $-866.11 | $-239.52 | $68.48 |
| ON | $-1,596.52 | $-402.99 | $-23.04 | $12.01 |

## H1 configuration sweep (full year, costs on)

| config | P/L | trades | win% | PF | H1 | H2 |
|---|---|---|---|---|---|---|
| default 9/21 TP1/2/3 + SL1.5 | $68.48 | 263 | 41.8% | 1.09 | $38.87 | $29.61 |
| wide TP 2/4/6 + SL 2.0 | $227.02 | 263 | 39.2% | 1.22 | $147.46 | $72.11 |
| wider TP 3/6/9 + SL 3.0 | $255.90 | 263 | 36.9% | 1.22 | $173.35 | $78.09 |
| stop only SL 2.0 + reversal | $226.50 | 263 | 30.4% | 1.19 | $160.36 | $70.06 |
| single TP 3.0 + SL 2.0 | $204.22 | 263 | 37.3% | 1.19 | $130.13 | $73.05 |
| wide + ATR choppiness filter | $-83.46 | 101 | 36.6% | 0.84 | $-39.44 | $-51.47 |
| wide, long only | $118.59 | 132 | 40.9% | 1.25 | $75.64 | $42.95 |
| wide, short only | $108.43 | 131 | 37.4% | 1.2 | $71.82 | $29.16 |
| wide 12/26 EMA | $120.84 | 201 | 37.8% | 1.14 | $82.82 | $31.45 |
| wide 50/200 SMA | $-9.43 | 30 | 30.0% | 0.94 | $11.44 | $-20.87 |

Chart: results/universal_signal.png

Reference points from the same repo: S7 order-block retest +$702 (2022), EMA 9/12 pure-reverse -$5,446 (2022).

## Finding

* The default configuration loses on M1/M5/M15 and only breaks even on H1 (+$68 for the year). Cost is the killer on the fast timeframes: the M1 run pays $3,344 of spread over 16,720 trades, and even with zero costs the M1 signal is still -$360 (no edge there).
* The ATR choppiness filter helps a lot on the fast timeframes (M1 -$3,704 -> -$1,597, M5 -$866 -> -$403, M15 -$240 -> -$23) but does not make them positive, and on H1 it HURTS (-$83 on the wide config).
* On H1 the edge appears only with WIDER targets: TP 3/6/9 ATR + SL 3.0 ATR gives +$256 (PF 1.22, 36.9% win, H1 +$173 / H2 +$78). The default 1/2/3 targets are too small relative to the noise; larger stops survive the whipsaw.
* Reference: our S7 order-block retest made +$702 on the same 2022 data, and the plain EMA 9/12 reverse system lost -$5,446.

Practical take: this indicator is a signal tester, and its default settings are not a strategy. If used at all, use H1 + wide ATR targets, and do not run the preset crosses on M1-M15 on gold.
