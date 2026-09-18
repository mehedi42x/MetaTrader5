# XAUUSD Backtest Report — Gold Trend-Momentum v1 (M15)

**Period:** 2022-02-02 23:45:00 → 2022-03-04 23:45:00 (30 days, 2015 M15 bars)
**Data:** XAUUSD M15, Dukascopy-sourced (ejtraderLabs/historical-data), last 1 month of file
**Starting balance:** $10,000 | **Risk/trade:** 1.0% | **SL:** 2.0xATR | **TP:** 4.0xATR (1:2 RR) | **Session:** 07:00-21:00 GMT | **Costs:** spread $0.35/oz + slippage $0.1/oz

## Results (1 month)

- Trades: **25** (Long 16 / Short 9)
- Win rate: **52.0%** (13W / 12L; TP exits 13, SL exits 12)
- Net P/L: **$1,121.62 (+11.22%)** → End balance $11,121.62
- Profit factor: **1.77** | Expectancy: **$44.86/trade** | Avg R: **0.44R**
- Avg win $199.02 / Avg loss $-122.13 | Max win $212.28 / Max loss $-132.75
- Max drawdown: **$-503.91 (-4.5%)** | Sharpe (daily): **4.69**

## Strategy rules

- Trend: Close > EMA20 > EMA50 → LONG only; mirror for SHORT
- Trigger: RSI(14) crosses 50 in trend direction (momentum continuation)
- Signal on bar close → entry next bar open. One position at a time. No martingale/grid/hedging.

## Honesty note (robustness check)

Same settings on adjacent months: Dec-2021 +3.1% (PF 1.18), Jan-2022 **-15.0%** (PF 0.47, choppy/range month), Feb-2022 +11.2% (PF 1.77). This is a trend-following system: it earns in trending months and bleeds in sideways months. One month is a short sample — forward-test on demo before any real money, keep risk ≤1%, and consider pausing it in clearly ranging markets.

## Files

- `results/trades.csv` — every trade | `results/equity_curve.csv` — equity | `results/backtest_chart.png` — price + trades + equity + drawdown
- `mql5/XAUUSD_GoldTrendMomentum.mq5` — same strategy as a MetaTrader 5 Expert Advisor
