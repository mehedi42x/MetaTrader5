# XAUUSD Backtest Report — EMA 9/12 on Renko-100 (real M1 bricks)

**Period:** 2022-02-02 18:20:00 → 2022-03-04 16:55:00 (30 days, 6954 renko bricks)
**Chart:** Renko, fixed brick $1.0 (= 100 points), built from real XAUUSD M1 (tiumbj/M1_XAUUSD, last 1 month of window)
**Starting balance:** $10,000 | **Lot:** fixed 0.1 | **Exit:** opposite crossover (reverse, always in market) | **Costs:** spread $0.35/oz + slippage $0.1/oz
**Entry filter:** trend (EMA200) + min distance $1.0 from EMA12 + 20-brick cooldown — blocked 354 raw crosses

## Results (1 month)

- Trades: **85** (Long 52 / Short 33)
- Win rate: **37.6%** (32W / 53L)
- Net P/L: **$497.50 (+4.98%)** → End balance $10,497.50
- Profit factor: **1.35** | Expectancy: **$5.85/trade**
- Avg win $59.56 / Avg loss $-26.58 | Max win $325.5 / Max loss $-44.5
- Max drawdown: **$-339.5 (-3.17%)** | Sharpe (daily): **2.95**

## System rules (Renko + crossover ONLY)

- Renko-100 bricks (brick = $1.0); BUY when EMA9 crosses ABOVE EMA12; SELL on cross below
- Signal on brick close → entry at next brick open (= completed brick close).
- ENTRY FILTER: only trade with the EMA200 trend, at least $1.0 away from EMA12, and 20 bricks after the previous exit (blocked 354 crosses).
- Opposite cross closes & reverses — exits are never filtered. No RSI, no SL/TP. Fixed lot.

## Filter verdict (this run)

Renko-100 unfiltered was **-$566 (-5.7%)** in Feb-2022 (439 trades, PF 0.92) and **-13.8%** in Jan. With the entry filter the same month gives **+$497 (+4.98%)** (85 trades, PF 1.35, max DD -3.2%) and Jan improves to -2.6%. The filter cuts ~80% of the trades — exactly the whipsaw crosses that were paying $4.50 spread each.

Sensitivity: 14 of 20 neighbouring settings (distance 0.8-1.5 $ x cooldown 0-50) are positive over Jan+Feb, so this is not a single lucky parameter set — but Jan is still slightly negative, so the edge is modest. See `results/filters_compare.png` and `python3 test_filters.py`.

## Files

- `results/trades.csv` — every trade | `results/equity_curve.csv` — equity | `results/backtest_chart.png` — chart
- `mql5/XAUUSD_EmaCross.mq5` — EA (attach it to a Renko offline chart in MT5)
