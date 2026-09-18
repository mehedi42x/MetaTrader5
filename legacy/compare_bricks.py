"""Compare Renko brick 50 ($0.50) vs 100 ($1.00) — bricks built from REAL M1 data.

Same system both sides: EMA 9/12 crossover only, reverse exit, fixed 0.10 lot,
spread $0.35/oz + slippage $0.10/oz. Test month Feb-2022 + Jan-2022 validation.

Usage:  python3 compare_bricks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals, add_filters
from src.backtest import run_backtest
from src.renko import build_renko

DATA = "data/xauusd_m1_slice.csv"
BRICKS = [0.50, 1.00]
BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.35
SLIPPAGE = 0.10
TREND_SPAN = 200
# entry filter found by test_filters.py (trend + min distance from slow EMA + cooldown)
FILTER = dict(trend=True, min_dist=1.0, cooldown=20)
PERIODS = [
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
    ("Feb-2022 (1-month test)", "2022-02-02 23:45", "2022-03-04 23:59"),
]


def run_one(bricks_df, t0, t1, entry_filter=None):
    d = bricks_df[bricks_df.time <= t1].copy().reset_index(drop=True)
    return run_backtest(d, t0, balance0=BALANCE0, spread=SPREAD,
                        slippage=SLIPPAGE, exit_mode="reverse", fixed_lot=FIXED_LOT,
                        entry_filter=entry_filter)


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    print(f"M1 source bars: {len(m1)} ({m1.time.min()} -> {m1.time.max()})\n")
    os.makedirs("legacy", exist_ok=True)

    allres, curves = {}, {}
    for b in BRICKS:
        name = f"Renko-{int(b * 100)}"
        rx = add_filters(add_signals(add_indicators(build_renko(m1, b))), TREND_SPAN)
        rx.to_csv(f"legacy/xauusd_renko{int(b * 100)}_m1_bricks.csv", index=False)
        print(f"== {name} (brick ${b}) -> {len(rx)} bricks ==")
        for label, t0, t1 in PERIODS:
            for tag, flt in (("unfiltered", None), ("filtered", FILTER)):
                tr, eq, s = run_one(rx, t0, t1, flt)
                allres[(name, label, tag)] = s
                if "Feb" in label:
                    curves[(name, tag)] = eq
                    if tag == "unfiltered":
                        tr.to_csv(f"legacy/trades_renko{int(b * 100)}.csv", index=False)
                nb = int(((rx.time >= t0) & (rx.time <= t1)).sum())
                print(f"  {label:24s} {tag:10s}: bricks={nb} trades={s['n_trades']:5d} "
                      f"win={s['win_rate']}% P/L=${s['net_pnl']} ({s['return_pct']}%) "
                      f"PF={s['profit_factor']} DD={s['max_dd_pct']}% exp=${s['expectancy']}")
        print()

    # ---------- verdict ----------
    feb, jan = PERIODS[1][0], PERIODS[0][0]
    print("=" * 96)
    print("50 vs 100 — unfiltered vs filtered (real M1 bricks)")
    print("=" * 96)
    print(f"{'':34s} {'Feb $':>10s} {'Feb %':>8s} {'Feb PF':>7s} {'Jan $':>10s} {'Jan %':>8s} "
          f"{'TOTAL $':>10s}")
    winners = {}
    for tag in ("unfiltered", "filtered"):
        for name in ("Renko-50", "Renko-100"):
            f = allres[(name, feb, tag)]
            j = allres[(name, jan, tag)]
            tot = f["net_pnl"] + j["net_pnl"]
            winners[(tag, name)] = tot
            print(f"{name + ' ' + tag:34s} {f['net_pnl']:>10.2f} {f['return_pct']:>7.2f}% "
                  f"{f['profit_factor']:>7} {j['net_pnl']:>10.2f} {j['return_pct']:>7.2f}% "
                  f"{tot:>10.2f}")
        w = "Renko-50" if winners[(tag, "Renko-50")] > winners[(tag, "Renko-100")] else "Renko-100"
        print(f"  -> {tag} winner (2-month): {w}")
    print()
    w = "Renko-50" if winners[("unfiltered", "Renko-50")] > winners[("unfiltered", "Renko-100")] else "Renko-100"
    print(f">>> WINNER 50v100: {w} <<<")

    # ---------- comparison chart (Feb equity curves overlaid) ----------
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    styles = [("Renko-50", "-", "#1f77b4"), ("Renko-100", "-", "#ff7f0e")]
    sf = allres[("Renko-50", feb, "filtered")]
    s1 = allres[("Renko-100", feb, "filtered")]
    bf = allres[("Renko-50", feb, "unfiltered")]
    b1 = allres[("Renko-100", feb, "unfiltered")]
    for col, tag in enumerate(("unfiltered", "filtered")):
        ax1, ax2 = axes[0][col], axes[1][col]
        for name, ls, c in styles:
            eq = curves[(name, tag)]
            s = allres[(name, feb, tag)]
            ax1.plot(pd.to_datetime(eq["time"]), eq["equity"], ls=ls, color=c, lw=1.4,
                     label=f"{name}: {s['return_pct']:+.2f}% ({s['n_trades']} trd, PF {s['profit_factor']})")
            import numpy as np
            ev = np.append([BALANCE0], eq["equity"].to_numpy())
            pk = np.maximum.accumulate(ev)
            ax2.plot(pd.to_datetime(eq["time"]), ((ev - pk) / pk * 100)[1:], color=c, lw=1.0)
        ax1.axhline(BALANCE0, color="gray", ls="--", lw=0.8)
        ax1.set_title(("Raw crossover (no filter)" if tag == "unfiltered"
                       else "With new entry filter (trend200 + $1.0 dist + cd20)"), fontsize=11)
        ax1.legend(fontsize=8, loc="lower left")
        ax1.grid(alpha=0.3)
        ax1.set_ylabel("Equity ($)")
        ax2.set_ylabel("DD %")
        ax2.grid(alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.suptitle("Renko-50 vs Renko-100 — real M1 bricks, Feb-2022, 0.10 lot, "
                 "spread $0.35 + slip $0.10", fontsize=12)
    fig.tight_layout()
    fig.savefig("legacy/compare_50v100.png", dpi=120)
    plt.close(fig)
    print("Saved: legacy/compare_50v100.png (+ trades_renko50/100.csv)")

if __name__ == "__main__":
    main()
