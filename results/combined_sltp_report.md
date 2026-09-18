# S7 + S1 — SL/TP variant test (2022, 0.01 lot, $0.20/trade)

Purpose: the TradingView script must offer SL and TP signals, so every variant was measured first. Half the stop/target settings destroy the edge; the defaults in the Pine script are the ones shown here as faithful.

## S7 alone (M1)

| variant | net $ | trades | win% | PF | max DD $ | exits |
|---|---|---|---|---|---|---|
| faithful: OB-fail close, no TP | 702.06 | 1337 | 21.6% | 1.67 | -40.04 | {'OB_FAIL': 950, 'FLIP': 387} |
| wick stop at block far side | 631.54 | 1345 | 15.9% | 1.79 | -36.94 | {'SL': 1060, 'FLIP': 285} |
| OB-fail close + 2R target | -11.89 | 1944 | 57.5% | 0.99 | -48.56 | {'TP': 1172, 'OB_FAIL': 591, 'FLIP': 181} |
| wick stop + 2R target | -71.26 | 1945 | 49.8% | 0.91 | -80.70 | {'TP': 1003, 'SL': 876, 'FLIP': 66} |
| ATR 2.0 stop + ATR 4.0 TP | 558.97 | 1802 | 49.7% | 1.5 | -24.42 | {'TP': 893, 'SL': 735, 'FLIP': 174} |
| ATR 2.0 stop only | 597.30 | 1263 | 20.2% | 1.51 | -57.39 | {'SL': 806, 'FLIP': 456, 'END': 1} |

## S1 alone (M5)

| variant | net $ | trades | win% | PF | max DD $ | exits |
|---|---|---|---|---|---|---|
| faithful: flip only, no SL/TP | 214.96 | 278 | 38.1% | 1.15 | -230.56 | {'FLIP': 277, 'END': 1} |
| ATR 2.0 stop only | 141.35 | 399 | 15.3% | 1.14 | -155.85 | {'SL': 323, 'FLIP': 76} |
| ATR 2.0 stop + ATR 4.0 TP | 82.90 | 482 | 36.7% | 1.09 | -145.34 | {'SL': 302, 'TP': 176, 'FLIP': 4} |
| no stop + ATR 4.0 TP | 216.31 | 419 | 69.2% | 1.16 | -127.12 | {'TP': 288, 'FLIP': 130, 'END': 1} |
| ATR 3.0 stop + 3R target | 95.79 | 424 | 28.1% | 1.07 | -277.89 | {'SL': 276, 'TP': 109, 'FLIP': 39} |

## Combined book (one account)

| configuration | net $ | trades | win% | PF | max DD $ |
|---|---|---|---|---|---|
| faithful (both legs unchanged) | 917.02 | 1615 | 24.5% | 1.37 | -167.15 |
| S7 wick stop + S1 faithful | 846.50 | 1623 | 19.7% | 1.38 | -163.26 |
| S7 faithful + S1 ATR 2/4 | 784.96 | 1819 | 25.6% | 1.4 | -117.22 |
| S7 ATR 2/4 + S1 ATR 2/4 | 641.87 | 2284 | 47.0% | 1.31 | -61.88 |
| S7 wick+2R + S1 ATR 2/4 | 11.64 | 2427 | 47.2% | 1.01 | -130.14 |
