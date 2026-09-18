# XAUUSD Backtest Report — EMA 9/12 on RENKO-50 (M15 source)

**Period:** 2022-02-03 01:30:00 → 2022-03-04 23:45:00 (30 days, 8424 renko bricks)
**Chart:** Renko, fixed brick $0.50 (= 50 points), built from XAUUSD M15 (Dukascopy-sourced, last 1 month of file)
**Starting balance:** $10,000 | **Lot:** fixed 0.1 | **Exit:** opposite crossover (reverse, always in market) | **Costs:** spread $0.35/oz + slippage $0.1/oz

## Results (1 month)

- Trades: **485** (Long 243 / Short 242)
- Win rate: **36.7%** (178W / 307L)
- Net P/L: **$2,857.50 (+28.58%)** → End balance $12,857.50
- Profit factor: **1.54** | Expectancy: **$5.89/trade**
- Avg win $45.58 / Avg loss $-17.12 | Max win $325.5 / Max loss $-29.5
- Max drawdown: **$-442.5 (-4.35%)** | Sharpe (daily): **6.83**

## System rules (Renko + crossover ONLY)

- Renko-50 bricks (brick = $0.5); BUY when EMA9 crosses ABOVE EMA12; SELL on cross below
- Signal on brick close → entry at next brick open (= completed brick close).
- Opposite cross closes & reverses. No RSI, no session filter, no SL/TP. Fixed lot.

## Files

- `data/xauusd_renko50_bricks.csv` — all renko bricks | `results/trades.csv` — every trade
- `results/equity_curve.csv` — equity | `results/backtest_chart.png` — chart
- `mql5/XAUUSD_EmaCross.mq5` — EA (attach it to a Renko-50 offline chart in MT5)
