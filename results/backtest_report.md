# XAUUSD Backtest Report — EMA 9/12 Crossover ONLY (M15)

**Period:** 2022-02-02 23:45:00 → 2022-03-04 23:45:00 (30 days, 2015 M15 bars)
**Data:** XAUUSD M15, Dukascopy-sourced (ejtraderLabs/historical-data), last 1 month of file
**Starting balance:** $10,000 | **Lot:** fixed 0.1 | **Exit:** opposite crossover (reverse, always in market) | **Costs:** spread $0.35/oz + slippage $0.1/oz

## Results (1 month)

- Trades: **109** (Long 55 / Short 54)
- Win rate: **29.4%** (32W / 77L)
- Net P/L: **$777.20 (+7.77%)** → End balance $10,777.20
- Profit factor: **1.3** | Expectancy: **$7.13/trade**
- Avg win $104.8 / Avg loss $-33.46 | Max win $473.8 / Max loss $-265.4
- Max drawdown: **$-744.2 (-6.64%)** | Sharpe (daily): **1.61**

## Strategy rules (crossover ONLY — all other logic removed)

- BUY when EMA9 crosses ABOVE EMA12; SELL when EMA9 crosses BELOW EMA12
- Signal on bar close → entry next bar open. Opposite cross closes & reverses.
- No RSI, no session filter, no SL/TP. Fixed lot every trade.

## Files

- `results/trades.csv` — every trade | `results/equity_curve.csv` — equity | `results/backtest_chart.png` — price + trades + equity + drawdown
- `mql5/XAUUSD_EmaCross.mq5` — same system as a MetaTrader 5 Expert Advisor
