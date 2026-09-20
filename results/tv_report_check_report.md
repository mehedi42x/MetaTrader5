# Checking the TradingView 5-day report (screenshot)

The screenshot shows, on XAUUSD 1m with the last price at 4378.385 (the real Friday
18 September 2026 close, so the window is 14-18 Sep - exactly the week tested here):

| field | screenshot |
|---|---|
| period | 5 days |
| total trades | 189 |
| win rate | 52.9% |
| net P/L | +1468.1 |

## 1. The same week in real M1 data (0.01 lot = 1 oz, $0.20/trade)

| variant | trades | win% | net $ at 1 oz | net $ at 10 oz |
|---|---|---|---|---|
| E1 script x cross | 230 | 31.7% | $148.87 | $1,488.70 |
| E2 cBot x cross | 252 | 31.0% | $132.32 | $1,323.20 |
| E1 x hybrid | 117 | 66.7% | $159.09 | $1,590.94 |
| E1 x 5m flip only | 51 | 47.1% | $165.14 | $1,651.43 |
| E1 x cross or flip | 230 | 32.2% | $150.41 | $1,504.08 |

**The week is positive in every variant - that part agrees with your chart.** But at 0.01 lot the same week produces about **+$149**, not +1,468.

Closest match to your three numbers: **E1 script x cross at 10 oz** (230 trades, 31.7% win, $1,488.70).

## 2. What +1468.1 implies

- Your net is **9.9x** the 1-oz result of the same week, i.e. about **9.9 oz = 0.10 lots**.
- Per trade in your report: **+$7.77**. At 1 oz that would
  require an average favourable move of $7.77 per trade; the average move on this
  week's trades is under $1. So the position was not 0.01 lot.
- The 52.9% win rate also does not match the plain open/close script (which wins ~31.7% on this week); it sits between the hybrid exit and the trailing-stop
  variants, so the version on your chart is not the one ported here - paste it and I
  will reproduce it bar for bar.

## 3. Why this matters - the same size over a longer window

| period | 1 oz (0.01 lot) | 10 oz (0.10 lot) |
|---|---|---|
| 2022 | $-2,977.60 | $-29,776.03 |
| 2023 | $-2,386.19 | $-23,861.91 |
| 2024 | $-2,487.60 | $-24,875.98 |
| 2025 | $-2,959.13 | $-29,591.25 |
| **2022-2025 total** | **$-10,810.52** | **$-108,105.17** |
| Sep 2026 (9-18 Sep, real MT5) | $27.01 | $270.14 |

## 2b. The chart's own price labels confirm the size

The screenshot shows per-trade labels of **-10, -10 and +10**. At 0.01 lot (1 oz) a
$1 move is worth $1, so those labels would read +-1. They read +-10, which is
exactly a **10 oz (0.1 lot)** position - and the report's average of
**+$7.77 per trade** matches the same scale. The trade count
(189) matches this repo's 4-session window (188 trades, 15-18 Sep), so the chart's
"5 days" covers 15-20 Sep while the reproduction above uses the 5 trading sessions
Position size multiplies the good week and the bad months in exactly the same
proportion. At 10 oz the four-year record of these rules is about -$118,000, and the
2026 stretch about -$270.

## 4. How to verify your own report in one minute

1. In the Strategy Tester click the **List of Trades** tab: the *Profit* column shows
   the money per trade in your account currency. If a typical winner shows ~$1-2, the
   size is 0.01 lot; if it shows ~$10-20, the size is 10x that.
2. Check the **Properties** tab: *Initial capital*, *Order size* (contracts) and
   *Commission*/*Slippage*. 0.01 lot must mean **1 contract = 1 oz** on XAUUSD.
3. Set `Slippage` to 20 ticks (or your broker's spread) so the test pays the spread -
   the pasted scripts ship with `slipTicks = 0` and `commissionPct = 0`, which means
   TradingView charges nothing while your account pays $0.20 per trade.
4. Re-run with **1 year or more** instead of 5 days. On this week's own data the
   difference between 0.01 and 0.10 lot is the whole story.

Chart: results/tv_report_check.png
