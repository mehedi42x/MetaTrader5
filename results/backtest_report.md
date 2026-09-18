# XAUUSD Backtest Report — EMA 9/12 on Renko-100 (real M1 bricks)

**Period:** 2022-02-02 18:20:00 → 2022-03-04 16:55:00 (30 days, 6954 renko bricks)
**Chart:** Renko, fixed brick $1.0 (= 100 points), built from real XAUUSD M1 (tiumbj/M1_XAUUSD, last 1 month of window)
**Starting balance:** $10,000 | **Lot:** fixed 0.1 | **Exit:** opposite crossover (reverse, always in market) | **Costs:** spread $0.35/oz + slippage $0.1/oz

## Results (1 month)

- Trades: **439** (Long 220 / Short 219)
- Win rate: **27.6%** (121W / 318L)
- Net P/L: **$-565.50 (-5.66%)** → End balance $9,434.50
- Profit factor: **0.92** | Expectancy: **$-1.29/trade**
- Avg win $54.84 / Avg loss $-22.64 | Max win $365.5 / Max loss $-54.5
- Max drawdown: **$-1435.5 (-13.38%)** | Sharpe (daily): **-1.29**

## System rules (Renko + crossover ONLY)

- Renko-100 bricks (brick = $1.0); BUY when EMA9 crosses ABOVE EMA12; SELL on cross below
- Signal on brick close → entry at next brick open (= completed brick close).
- Opposite cross closes & reverses. No RSI, no session filter, no SL/TP. Fixed lot.

## 50v100 verdict

Feb-2022 on real M1 bricks: Renko-50 = **-$3,384 (-33.8%)**, 1281 trades; Renko-100 = **-$566 (-5.7%)**, 439 trades. Jan-2022: 50 = -30.2%, 100 = -13.8%. Renko-100 wins clearly — smaller bricks overtrade and bleed out in spread costs (50 paid $5,764 in costs vs $1,976 for 100). Neither is profitable after costs; see `python3 compare_bricks.py` and `results/compare_50v100.png`.

## Files

- `results/trades.csv` — every trade | `results/equity_curve.csv` — equity | `results/backtest_chart.png` — chart
- `mql5/XAUUSD_EmaCross.mq5` — EA (attach it to a Renko offline chart in MT5)
