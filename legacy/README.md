# Legacy: Renko experiments (superseded)

The Renko branch of this project was tested here and **abandoned** — on
2026-09-18 the user asked for plain candlesticks on M3 instead.

What these files contain (kept for reference only):

- `compare_bricks.py` — built Renko-50 / Renko-100 bricks from real M1 data and
  backtested them. Result: Renko-50 **-33.8%** (Feb-2022, 1281 trades, drowned in
  $5,764 of spread), Renko-100 **-5.7%** (439 trades). Renko-100 won both raw and
  filtered, but neither is usable.
- `test_filters.py` — entry-filter sweep (trend200 + $ distance from EMA12 +
  cooldown). Turned Renko-100 Feb into **+4.98%** (85 trades, PF 1.35) and cut Jan
  to -2.6%; 14/20 neighbouring parameter sets positive. Interesting, but the
  M3-candle data below showed the same filter does **not** save M3 candles
  (Feb -7.0%, Jan -3.4%).
- `xauusd_renko*_m1_bricks.csv` — the brick series (time, open, close, high, low,
  direction, ema…).
- `compare_50v100.png`, `filters_compare.png` — the charts from those tests.

**Run them from the repo root** (`python3 legacy/compare_bricks.py`) — they import
`src.*` from there and write their outputs into `legacy/`.

Current system lives in the repo root: **`run_backtest.py` = EMA 9/12 crossover on
normal M3 candles.**
