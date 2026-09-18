# EMA MTF (1m & 5m) + Bollinger Bands — test report

Python port of the pasted Pine v6 strategy (visuals dropped, logic identical):
EMA 6/9 crossover on the chart timeframe, filtered by (a) EMA 9/12 on the 5-minute timeframe taken from the last COMPLETED 5m bar (no repaint) and (b) close above/below the Bollinger middle line (SMA 20). A raw opposite cross closes the position. Market orders fill at the next bar's open.

Sizing / costs = house rules: 0.01 lot (1 oz, exactly the script's lotSize 1.0 x leverage 1.0) and $0.20 spread per round trip. Data: real XAUUSD M1 (DAT_MT_XAUUSD_M1_2024/2025).

## Results

| window | setup | trades | net $ | win% | PF | max DD $ | long/short | avg/trade |
|---|---|---|---|---|---|---|---|---|
| 3 days (29-31 Dec 2025) | M1 chart + 5m trend | 127 | $12.71 | 26.8% | 1.05 | $-55.62 | 44/83 | $0.100 |
| 3 days (29-31 Dec 2025) | M5 chart + 5m trend | 12 | $-9.08 | 33.3% | 0.78 | $-24.29 | 4/8 | $-0.756 |
| 3 days (29-31 Dec 2025) | M5 chart + 15m trend | 27 | $60.74 | 25.9% | 1.59 | $-34.35 | 8/19 | $2.250 |
| 1 month (Dec 2025) | M1 chart + 5m trend | 1080 | $-352.60 | 25.7% | 0.78 | $-378.96 | 593/487 | $-0.326 |
| 1 month (Dec 2025) | M5 chart + 5m trend | 97 | $-139.33 | 23.7% | 0.57 | $-174.08 | 52/45 | $-1.436 |
| 1 month (Dec 2025) | M5 chart + 15m trend | 190 | $-153.44 | 23.7% | 0.76 | $-255.57 | 96/94 | $-0.808 |
| 1 month (Dec 2024, regime check) | M1 chart + 5m trend | 995 | $-185.93 | 26.9% | 0.75 | $-202.74 | 486/509 | $-0.187 |
| 1 month (Dec 2024, regime check) | M5 chart + 5m trend | 95 | $-43.18 | 21.1% | 0.66 | $-51.82 | 48/47 | $-0.454 |
| 1 month (Dec 2024, regime check) | M5 chart + 15m trend | 189 | $-30.33 | 21.7% | 0.88 | $-75.10 | 108/81 | $-0.160 |
| 365 days (script default) = 2025 | M1 chart + 5m trend | 12517 | $-2,959.12 | 25.7% | 0.8 | $-2,982.56 | 6932/5585 | $-0.236 |
| 365 days (script default) = 2025 | M5 chart + 5m trend | 1046 | $235.60 | 27.0% | 1.1 | $-200.52 | 590/456 | $0.225 |
| 365 days (script default) = 2025 | M5 chart + 15m trend | 2149 | $550.58 | 28.8% | 1.11 | $-341.57 | 1257/892 | $0.256 |
| full 2024 (second year) | M1 chart + 5m trend | 12369 | $-2,487.60 | 24.5% | 0.71 | $-2,492.00 | 6686/5683 | $-0.201 |
| full 2024 (second year) | M5 chart + 5m trend | 1163 | $-234.43 | 24.9% | 0.83 | $-274.18 | 630/533 | $-0.202 |
| full 2024 (second year) | M5 chart + 15m trend | 2273 | $-343.43 | 25.3% | 0.88 | $-426.68 | 1292/981 | $-0.151 |

## Verdict

**The system has no edge on XAUUSD, and the spread destroys what is left of it.**

* **M1 chart (the script's default setup)** - 12,517 trades in 2025 -> **-$2,959** (PF 0.80). The spread alone costs **-$2,503**. With zero cost it is still **-$456**, 
so there is no raw edge either; in 2024 it is -$2,488 (zero cost: -$14, i.e. flat).
* **M5 chart + 5m trend** - 2025 +$236, 2024 **-$234**; Dec 2025 -$139 (even with zero cost -$120). A one-year positive result that flips sign in the other year is noise.
* **M5 chart + 15m trend** - 2025 +$551, 2024 **-$343**, Dec 2025 -$153. Same story.
* The last 3 days (29-31 Dec 2025) are pure noise: M1 +$12.71 on 127 trades (average +$0.10/trade), M5 -$9.08. Three days cannot prove anything, and the month (Dec 2025) that contains them is negative on every setting.
* The spread ($0.20) is small next to the average winner on M1 ($4.51) but the gross edge is already negative (avg loss on the year: -$1.60), so every extra trade digs the hole deeper: 12,517 trades x $0.20 = $2,503 of pure spread.

### Why the TradingView numbers will look better

1. The script ships with `spreadPoints = 0` and `slippageTicks = 0`, so its own report table subtracts **nothing**. With a real 20-point gold spread the table would show roughly the numbers above.
2. `initial_capital = 100000` makes the percentages look tiny and hides the drawdown; the 2025 M1 drawdown is -$2,983 on 0.01 lot.
3. TradingView does not model the spread at all for `strategy()` orders.

**Net:** the Bollinger middle filter and the 5m EMA trend filter both reduce trade quality here; the 6/9 EMA crossover on M1 is simply too fast for a market that pays a 20-point spread.

Chart: results/ema_mtf_bb.png
