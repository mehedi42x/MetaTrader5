# XAUUSD Backtest Report — EMA 9/12 crossover on original M1 candles

**Chart:** original XAUUSD **M1** candles (real broker data, tiumbj/M1_XAUUSD)
**Cost:** **spread only, 20 points = $0.2/oz** = $2.00 per 0.10-lot round trip (no slippage added)
**Test period:** 2022-02-02 16:59:00 → 2022-03-04 16:59:00 (last 30 days, 30209 M1 candles)
**Balance:** $10,000 | **Lot:** fixed 0.1 | **Exit:** opposite crossover (reverse, always in market)

## Result (last 30 days, Feb-2022)

- Trades: **1907** (Long 954 / Short 953)
- Win rate: **23.2%** (443W / 1464L)
- Net P/L: **$-4,063.46 (-40.63%)** → end balance $5,936.54
- Profit factor: **0.7** | Expectancy: **$-2.13/trade**
- Max drawdown: **-40.68%** | Sharpe (daily): **-12.64**
- Spread paid: **$3,814.00** (1907 x $2.00)

## Full window (Jan 2 – Mar 4, 2 months)

- Trades **3809** | win 23.7% | P/L **$-8,817.84 (-88.18%)** | PF 0.64 | max DD -88.37%

## Cost sensitivity (same Feb signals, 0.10 lot)

| cost setting | net P/L | return | PF | spread paid | gross before cost |
|---|---|---|---|---|---|
| spread 20 pts only (used here) | $-4,063.46 | -40.63% | 0.7 | $3,814.00 | $-249.46 |
| spread 20 pts + slip 5 pts | $-5,016.96 | -50.17% | 0.65 | $4,767.50 | $-249.46 |
| spread 20 pts + slip 10 pts | $-5,970.46 | -59.70% | 0.6 | $5,721.00 | $-249.46 |
| old setting: 35 pts + slip 10 pts | $-8,830.96 | -88.31% | 0.49 | $8,581.50 | $-249.46 |

Reading the last column: the raw M1 crossover is roughly break-even *before* costs, so every point of spread decides profit or loss. At the old 35+10 pts setting the same signals lose $-8,830.96; at 20 pts only they lose $-4,063.46.

## System rules

- Original M1 candles; BUY on EMA9 cross above EMA12, SELL on cross below
- Signal on candle close → entry at next candle open (no lookahead)
- Opposite cross closes & reverses. Fixed lot. No SL/TP, no filter, no RSI.

## Files

- `data/xauusd_m1_slice.csv` — original M1 candles used here
- `results/trades.csv`, `results/equity_curve.csv`, `results/backtest_chart.png`
- `python3 compare_timeframes.py` — M1/M3/M5/M15 on the same system
- `legacy/` — old Renko experiments
