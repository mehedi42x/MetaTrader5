# XAUUSD Backtest Report — EMA 9/12 crossover on M3 candles

**Timeframe:** normal candlestick **M3** (built by resampling real XAUUSD M1, tiumbj/M1_XAUUSD)
**Test period:** 2022-02-02 16:57:00 → 2022-03-04 16:57:00 (30 days, 10071 M3 candles)
**Balance:** $10,000 | **Lot:** fixed 0.1 | **Exit:** opposite crossover (reverse, always in market) | **Costs:** spread $0.35/oz + slippage $0.1/oz

## Result (30 days)

- Trades: **618** (Long 309 / Short 309)
- Win rate: **22.7%** (140W / 478L)
- Net P/L: **$-3,062.52 (-30.63%)** → end balance $6,937.48
- Profit factor: **0.64** | Expectancy: **$-4.96/trade**
- Avg win $39.42 / avg loss $-17.95
- Max drawdown: **$-3063.97 (-30.64%)** | Sharpe (daily): **-8.87**
- Spread+slippage paid: **$2,781.00** (618 trades x $4.50)

## Full 2-month window (Jan 2 – Mar 4, sanity check)

- Trades: **1306** | Win rate 20.7% | P/L **$-7,560.50 (-75.60%)** | PF 0.54 | max DD -75.95%

## System rules

- M3 candles; BUY on EMA9 cross above EMA12, SELL on cross below
- Signal on candle close → entry at next candle open (no lookahead)
- Opposite cross closes & reverses. Fixed lot. No SL/TP, no filter, no RSI.

## Note

This replaces the Renko experiments (see `legacy/`). Renko-100 with a 3-part entry filter had shown +4.98% for Feb-2022, but on plain M3 candles the raw crossover gives the numbers above — compare the trade count and spread cost before choosing.

## Files

- `data/xauusd_m3_slice.csv` — M3 candles used here
- `results/trades.csv`, `results/equity_curve.csv`, `results/backtest_chart.png`
- `python3 compare_timeframes.py` — M1 vs M3 vs M5 vs M15 on the same system
