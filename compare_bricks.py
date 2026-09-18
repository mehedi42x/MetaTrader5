"""Compare Renko brick 50 ($0.50) vs 100 ($1.00) — bricks built from REAL M1 data.

Same system both sides: EMA 9/12 crossover only, reverse exit, fixed 0.10 lot,
spread $0.35/oz + slippage $0.10/oz. Test month Feb-2022 + Jan-2022 validation.

Usage:  python3 compare_bricks.py
"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals
from src.backtest import run_backtest
from src.renko import build_renko

DATA = "data/xauusd_m1_slice.csv"
BRICKS = [0.50, 1.00]
BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.35
SLIPPAGE = 0.10
PERIODS = [
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
    ("Feb-2022 (1-month test)", "2022-02-02 23:45", "2022-03-04 23:59"),
]


def run_one(bricks_df, t0, t1):
    d = bricks_df[bricks_df.time <= t1].copy().reset_index(drop=True)
    return run_backtest(d, t0, balance0=BALANCE0, spread=SPREAD,
                        slippage=SLIPPAGE, exit_mode="reverse", fixed_lot=FIXED_LOT)


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    print(f"M1 source bars: {len(m1)} ({m1.time.min()} -> {m1.time.max()})\n")
    os.makedirs("results", exist_ok=True)

    allres, curves = {}, {}
    for b in BRICKS:
        name = f"Renko-{int(b * 100)}"
        rx = add_signals(add_indicators(build_renko(m1, b)))
        rx.to_csv(f"data/xauusd_renko{int(b * 100)}_m1_bricks.csv", index=False)
        print(f"== {name} (brick ${b}) -> {len(rx)} bricks ==")
        for label, t0, t1 in PERIODS:
            tr, eq, s = run_one(rx, t0, t1)
            allres[(name, label)] = s
            if "Feb" in label:
                curves[name] = eq
                tr.to_csv(f"results/trades_renko{int(b * 100)}.csv", index=False)
            nb = int(((rx.time >= t0) & (rx.time <= t1)).sum())
            print(f"  {label}: bricks={nb} trades={s['n_trades']} win={s['win_rate']}% "
                  f"P/L=${s['net_pnl']} ({s['return_pct']}%) PF={s['profit_factor']} "
                  f"DD={s['max_dd_pct']}% exp=${s['expectancy']}")
        print()

    # ---------- verdict ----------
    f50 = allres[("Renko-50", "Feb-2022 (1-month test)")]
    f100 = allres[("Renko-100", "Feb-2022 (1-month test)")]
    j50 = allres[("Renko-50", "Jan-2022 (validation)")]
    j100 = allres[("Renko-100", "Jan-2022 (validation)")]
    tot50 = f50["net_pnl"] + j50["net_pnl"]
    tot100 = f100["net_pnl"] + j100["net_pnl"]
    winner = "Renko-50" if tot50 > tot100 else "Renko-100"
    print(f"2-month total (Jan+Feb): Renko-50 = ${tot50:.2f} | Renko-100 = ${tot100:.2f}")
    print(f">>> WINNER: {winner} <<<")

    # ---------- comparison chart (Feb equity curves overlaid) ----------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    for name, eq in curves.items():
        ax1.plot(pd.to_datetime(eq["time"]), eq["equity"], lw=1.2, label=name)
    ax1.axhline(BALANCE0, color="gray", ls="--", lw=0.8)
    ax1.set_title("Renko-50 vs Renko-100 — equity (Feb-2022, EMA 9/12 cross, 0.10 lot)")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax1.set_ylabel("Equity ($)")
    for name, eq in curves.items():
        import numpy as np
        ev = np.append([BALANCE0], eq["equity"].to_numpy())
        pk = np.maximum.accumulate(ev)
        dd = (ev - pk) / pk * 100
        ax2.plot(pd.to_datetime(eq["time"]), dd[1:], lw=1.0, label=name)
    ax2.set_ylabel("DD %")
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.tight_layout()
    fig.savefig("results/compare_50v100.png", dpi=120)
    plt.close(fig)
    print("Saved: results/compare_50v100.png (+ trades_renko50/100.csv)")


if __name__ == "__main__":
    main()
