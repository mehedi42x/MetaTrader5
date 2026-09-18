"""Same EMA 9/12 crossover system on normal candles of different timeframes.

M1 / M3 / M5 / M15 candles are resampled from the same real XAUUSD M1 data, so
the comparison is apples-to-apples: identical system, identical window, identical
costs (spread $0.35 + slippage $0.10 per oz, fixed 0.10 lot).

Usage:  python3 compare_timeframes.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals
from src.backtest import run_backtest

M1_DATA = "data/xauusd_m1_slice.csv"
TFS = [1, 3, 5, 15]
BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.35
SLIPPAGE = 0.10
COST_PER_TRADE = (SPREAD + SLIPPAGE) * FIXED_LOT * 100
PERIODS = [
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
    ("Feb-2022 (1-month test)", "2022-02-02 23:45", "2022-03-04 23:59"),
]


def resample_ohlc(m1, minutes):
    g = (m1.set_index("time").resample(f"{minutes}min")
         .agg(open=("open", "first"), high=("high", "max"),
              low=("low", "min"), close=("close", "last"), n=("close", "size")))
    return g[g.n > 0].drop(columns="n").reset_index()


def main():
    m1 = pd.read_csv(M1_DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    os.makedirs("results", exist_ok=True)
    rows, curves = [], {}
    for tf in TFS:
        candles = resample_ohlc(m1, tf)
        df = add_signals(add_indicators(candles))
        for label, t0, t1 in PERIODS:
            d = df[df.time <= t1].reset_index(drop=True)
            tr, eq, s = run_backtest(d, t0, balance0=BALANCE0, spread=SPREAD,
                                     slippage=SLIPPAGE, exit_mode="reverse",
                                     fixed_lot=FIXED_LOT)
            rows.append((tf, label, s))
            if "Feb" in label:
                curves[tf] = eq
        print(f"M{tf}: " + " | ".join(
            f"{label[:3]} {s['return_pct']:+.1f}% ({s['n_trades']} trd, PF {s['profit_factor']})"
            for tf_, label, s in rows if tf_ == tf))

    print("\n" + "=" * 96)
    print("EMA 9/12 crossover — normal candles, timeframe comparison (real XAUUSD M1 source)")
    print("=" * 96)
    print(f"{'TF':>4s} {'Feb $':>10s} {'Feb %':>8s} {'trades':>7s} {'win%':>6s} {'PF':>6s} "
          f"{'DD%':>8s} {'costs $':>9s} | {'Jan $':>10s} {'Jan %':>8s} {'2-mo $':>10s}")
    for tf in TFS:
        f = [s for t, l, s in rows if t == tf and "Feb" in l][0]
        j = [s for t, l, s in rows if t == tf and "Jan" in l][0]
        print(f"M{tf:<3d} {f['net_pnl']:>10.2f} {f['return_pct']:>7.2f}% {f['n_trades']:>7d} "
              f"{f['win_rate']:>5.1f}% {f['profit_factor']:>6} {f['max_dd_pct']:>7.2f}% "
              f"{f['n_trades'] * COST_PER_TRADE:>9.2f} | {j['net_pnl']:>10.2f} "
              f"{j['return_pct']:>7.2f}% {f['net_pnl'] + j['net_pnl']:>10.2f}")

    best = max(TFS, key=lambda tf: [s for t, l, s in rows if t == tf and "Feb" in l][0]["net_pnl"])
    print(f"\n>>> best timeframe on Feb: M{best}")

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = {1: "#7f7f7f", 3: "#1f77b4", 5: "#2ca02c", 15: "#ff7f0e"}
    for tf in TFS:
        eq = curves[tf]
        f = [s for t, l, s in rows if t == tf and "Feb" in l][0]
        ax.plot(pd.to_datetime(eq["time"]), eq["equity"], lw=1.5, color=colors[tf],
                label=f"M{tf}: {f['return_pct']:+.1f}% ({f['n_trades']} trd, PF {f['profit_factor']})")
    ax.axhline(BALANCE0, color="k", ls=":", lw=1)
    ax.set_title("EMA 9/12 crossover on normal candles — timeframe comparison "
                 "(Feb-2022, 0.10 lot, spread $0.35 + slip $0.10)")
    ax.set_ylabel("Equity ($)")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    fig.tight_layout()
    fig.savefig("results/tf_compare.png", dpi=120)
    print("Saved results/tf_compare.png")


if __name__ == "__main__":
    main()
