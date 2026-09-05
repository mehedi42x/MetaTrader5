# TFAM — Tick-Flow Absorption Momentum

Custom XAUUSD tick-microstructure strategy for MetaTrader 5.
**No indicators. No price action. No candles.** Only `bid`, `ask`, `timestamp`.

| Metric (20d, 10.03M ticks, 0.01 lot @ 800x) | Value |
|---|---|
| Net profit | **+$218.96 (+21.90%)** |
| Profit factor | **2.49** |
| Win rate | **68.63%** |
| Max drawdown | **−0.34%** |
| Trades | 969 (48/day, median hold 4.9s) |
| Monte-Carlo | 8/8 seeds profitable |

📄 **Full analysis → [REPORT.md](REPORT.md)**

## Layout
```
src/strategy.py      TFAM signal engine + entry/exit logic
src/tick_data.py     MT5 tick CSV loader + microstructure tick simulator
src/backtest.py      tick-by-tick backtester + 40 metrics
mql5/TFAM_Gold.mq5   live MT5 Expert Advisor (1:1 port)
results/             JSON results, trades.csv, equity_curve.png
```

## Dukascopy — 2 years of real ticks

```bash
bash run_dukascopy.sh          # download 2y XAUUSD ticks + run both strategies
```

`src/dukascopy.py` downloads and decodes Dukascopy's hourly `.bi5` LZMA tick
files (resumable cache, parallel workers) and writes MT5-format CSV.
Note: this sandbox blocks Dukascopy, so run it on your own machine —
see [docs/REAL_DATA_STATUS.md](docs/REAL_DATA_STATUS.md).

## Two strategies

| | TFAM | QAS |
|---|---|---|
| Signal | trade-flow momentum (where price went) | **quote asymmetry** (how bid/ask move apart) |
| Core metric | flow z-score + directional efficiency | one-sided quote revisions + spread skew |
| Exits | TP/SL/flow-flip/trail/time | TP/SL/breakeven/pressure-decay/time |
| Run | `src/report.py` | `src/run_scalper.py` |

## Real tick data
Full real-data pipeline is ready (`src/mt5_loader.py` + `src/report.py`).
Your `XAUUSD.txt` (480 MB, Git LFS) could not be fetched — this sandbox blocks
GitHub's CDN hosts. See **[docs/REAL_DATA_STATUS.md](docs/REAL_DATA_STATUS.md)**.

```bash
.venv/bin/python src/report.py /path/to/XAUUSD.txt
```

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install numpy pandas matplotlib
.venv/bin/python src/backtest.py
```

⚠️ Backtest uses a seeded microstructure simulator (no broker feed in sandbox).
Re-validate with your own MT5 tick export via `load_mt5_ticks()` before live use.
Requires a raw/ECN account — costs are ~60% of gross profit.
