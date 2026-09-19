# EMA MTF (1m & 5m) + Bollinger Bands — full-year backtest on the older data

Faithful port of the pasted Pine v6 script (visuals dropped). Entry: EMA 6/9 crossover on the M1 chart + EMA 9/12 trend on M5 from the last CLOSED 5m bar (no repaint) + close above/below the Bollinger(20,2) middle. Exit: raw opposite EMA cross. Fills at the next bar's open. 0.01 lot (1 oz) and $0.20 spread per round trip (house rules); the script's own default of 0 spread is shown as a reference column.

Data: real XAUUSD M1 (github.com/tiumbj/M1_XAUUSD). 2023 = 371,000 bars approx, 2024 = 355,652, 2025 = 354,011.

## Results

| config | year | trades | net $ | win% | PF | max DD $ | avg/trade | gross $ | spread cost $ |
|---|---|---|---|---|---|---|---|---|---|
| M1 chart + M5 trend | 2023 | 10788 | $-2,388.70 | 21.6% | 0.6 | $-2,400.45 | $-0.221 | $-231.10 | $2,157.60 |
| M5 chart + M5 trend | 2023 | 976 | $-156.53 | 24.2% | 0.83 | $-213.51 | $-0.160 | $38.67 | $195.20 |
| M1 chart + M5 trend | 2024 | 12369 | $-2,490.24 | 24.5% | 0.71 | $-2,494.64 | $-0.201 | $-16.44 | $2,473.80 |
| M5 chart + M5 trend | 2024 | 1163 | $-234.52 | 24.9% | 0.83 | $-274.27 | $-0.202 | $-1.92 | $232.60 |
| M1 chart + M5 trend | 2025 | 12517 | $-2,960.13 | 25.7% | 0.8 | $-2,983.56 | $-0.236 | $-456.73 | $2,503.40 |
| M5 chart + M5 trend | 2025 | 1046 | $235.58 | 27.0% | 1.1 | $-200.49 | $+0.225 | $444.78 | $209.20 |

## Month by month — M1 chart + M5 trend ($)

| month | 2023 | 2024 | 2025 |
|---|---|---|---|
| Jan | -123.66 (961) | -202.24 (1072) | -355.47 (1092) |
| Feb | -256.20 (826) | -236.11 (971) | -119.08 (952) |
| Mar | -68.79 (815) | -83.12 (948) | -218.20 (1016) |
| Apr | -157.54 (660) | -95.39 (1055) | -284.04 (1005) |
| May | -159.09 (763) | -323.11 (1128) | -246.45 (1101) |
| Jun | -201.99 (778) | -216.48 (964) | -336.36 (1088) |
| Jul | -238.28 (725) | -233.88 (1111) | -329.72 (1100) |
| Aug | -362.11 (1200) | -175.12 (1054) | -314.82 (995) |
| Sep | -206.42 (975) | -262.79 (1020) | -237.18 (1040) |
| Oct | -205.99 (1048) | -314.45 (1079) | +69.39 (1079) |
| Nov | -283.81 (1074) | -161.73 (972) | -235.53 (969) |
| Dec | -124.82 (963) | -185.82 (995) | -352.67 (1080) |
| **Total** | **-2,388.70** (10788) | **-2,490.24** (12369) | **-2,960.13** (12517) |

## Verdict

**Three full years, three straight losses — and the loss is remarkably constant, which
means it is a structural cost problem, not bad luck in one market phase.**

| year | trades | net $ | gross (before spread) | spread cost | win% gross / net | PF |
|---|---|---|---|---|---|---|
| 2023 | 10,788 | -$2,388.70 | -$231.10 | $2,157.60 | 27.9% → 21.6% | 0.60 |
| 2024 | 12,369 | -$2,490.24 | -$16.44 | $2,473.80 | 29.0% → 24.5% | 0.71 |
| 2025 | 12,517 | -$2,960.13 | -$456.73 | $2,503.40 | 28.4% → 25.7% | 0.80 |

Key reads:

1. **The gross edge is zero to slightly negative** (-$231, -$16, -$457 before any cost).
   Even if the broker charged nothing, the system would not make money over a year.
2. **The spread costs ~$2,150-2,500 per year** because the system fires 11,000-12,500
   times. That is the whole loss: net = gross - cost, every single year.
3. **The win rate is only ~28% gross and ~25% net.** The average winner does not pay
   for three losers.
4. **Month by month it is almost monotonically negative**: 2023 = 12/12 negative months,
   2024 = 12/12, 2025 = 11/12 (the single positive month, October 2025, is +$69 out of a
   -$2,960 year — noise).
5. **M5 chart is not a rescue**: -$157 (2023), -$235 (2024), +$236 (2025) — sign flips,
   i.e. no stable edge; and it still loses money in two of three years.
6. **Compare with buy & hold 1 oz**: gold made +$236 / +$560 / +$1,693 in those years
   while this system lost $2,400-2,960. In 2025 gold rose 64% and the strategy lost 30%
   of the account.

### Why the 5-day September 2026 test looked good (+$148.84)

That window was an unusually trendy $200 swing (4435 → 4235 → 4435) on the newest data.
Trending windows favour an EMA crossover system; the three years above show what happens
in normal and ranging conditions. **A 5-day sample cannot overturn 35,000 trades of
evidence.**

### Bottom line

Do not trade this live. If a version of it is ever kept, the only lever that changes the
result is **trade frequency** — the entry has to be filtered hard so it fires a few
hundred times a year instead of 12,000, because at 12,000 trades the spread alone is
$2,400 a year. The best configuration measured in this repo remains **S7 order-block
retest (M1) + S1 swing flip (M5)**: +$917 on 2022 with 1,615 trades.

Chart: results/ema_years.png
