"""NEW entry filters for the EMA 9/12 Renko system (real M1-built bricks).

Baseline problem (compare_bricks.py): the crossover has a small gross edge but
spread bleed dominates -> Renko-100 -5.7% (Feb), Renko-50 -33.8%. Root cause =
whipsaw: too many crosses, each paying $4.50 per 0.10 lot round trip.

Filters tested here (entry gate only; exit = opposite cross, unchanged):
  trend200  : only buy above / sell below EMA200 of the brick series
  trend100  : same with EMA100
  dist0.5/1.0/1.5 : require |close - EMA12| >= X $ at the cross
              (the EMA9-EMA12 gap itself is tiny ~0.03, useless as a gate)
  cd10/20/50: cooldown — at least N bricks between trades
  combo     : trend200 + dist1.0 + cd20
  combo_slope: trend200 + dist1.0 + EMA12 5-brick slope agrees with direction

Usage:  python3 test_filters.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals
from src.indicators import ema
from src.renko import build_renko

BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.35
SLIPPAGE = 0.10
COST_PER_OZ = SPREAD + SLIPPAGE
OZ = FIXED_LOT * 100.0          # 0.10 lot = 10 oz
M1 = "data/xauusd_m1_slice.csv"
PERIODS = [
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
    ("Feb-2022 (1-month test)", "2022-02-02 23:45", "2022-03-04 23:59"),
]


def load_bricks(brick):
    m1 = pd.read_csv(M1, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    df = build_renko(m1, brick)
    df = add_signals(add_indicators(df))
    df["ema200"] = ema(df["close"], 200)
    df["ema100"] = ema(df["close"], 100)
    df["dist"] = (df["close"] - df["ema_slow"]).abs()   # $ distance from EMA12
    df["slope"] = df["ema_slow"].diff(5)                # EMA12 5-brick slope
    return df


# --------------------------------------------------------------- engine -----
def bt(df, t0, gate=None):
    """Same engine as src.backtest(exit_mode='reverse') when gate=None.
    `gate(i, direction, last_exit_idx)` may only BLOCK entries — exits always run."""
    o = df["open"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()
    sig = df["signal"].to_numpy()
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    bal = BALANCE0
    trades, eq_ts, eq_val = [], [], []
    pos, blocked = None, 0
    last_exit = -10**9

    def close(price, when):
        nonlocal bal, pos, last_exit
        pnl = (price - pos["entry"]) * pos["dir"] * OZ - COST_PER_OZ * OZ
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when, direction=pos["dir"],
                           entry=pos["entry"], exit=price, pnl=round(pnl, 2)))
        pos, last_exit = None, when

    for i in range(1, len(df)):
        if i >= start and sig[i - 1] != 0:
            d = int(sig[i - 1])
            if pos is not None and pos["dir"] != d:
                close(o[i], i)
            if pos is None:
                if gate is None or gate(i - 1, d, last_exit):
                    pos = dict(dir=d, entry=o[i], t=t[i], idx=i)
                else:
                    blocked += 1
        eq_ts.append(t[i])
        eq_val.append(bal)

    if pos is not None:
        close(float(df["close"].iloc[-1]), len(df) - 1)

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    if tr.empty:
        return tr, eq, dict(n_trades=0, net_pnl=0.0, return_pct=0.0, profit_factor=0.0,
                            win_rate=0.0, max_dd_pct=0.0, expectancy=0.0, blocked=blocked,
                            gross=0.0, costs=0.0)
    wins, losses = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    gl = -losses.pnl.sum()
    eqv = np.append([BALANCE0], eq.equity.to_numpy())
    peak = np.maximum.accumulate(eqv)
    dd = ((eqv - peak) / peak * 100).min()
    return tr, eq, dict(
        n_trades=len(tr), net_pnl=round(tr.pnl.sum(), 2),
        return_pct=round(tr.pnl.sum() / BALANCE0 * 100, 2),
        profit_factor=round(wins.pnl.sum() / gl, 2) if gl > 0 else float("inf"),
        win_rate=round(len(wins) / len(tr) * 100, 1),
        max_dd_pct=round(dd, 2), expectancy=round(tr.pnl.mean(), 2),
        gross=round(tr.pnl.sum() + len(tr) * COST_PER_OZ * OZ, 2),
        costs=round(len(tr) * COST_PER_OZ * OZ, 2), blocked=blocked)


# -------------------------------------------------------------- filters -----
def build_gates(df):
    close = df["close"].to_numpy()
    dist = df["dist"].to_numpy()
    slope = df["slope"].to_numpy()
    e200 = df["ema200"].to_numpy()
    e100 = df["ema100"].to_numpy()

    def trend(col):
        return lambda i, d, le: (close[i] > col[i]) if d == 1 else (close[i] < col[i])

    def dist_f(thr):
        return lambda i, d, le: dist[i] >= thr

    def cool(n):
        return lambda i, d, le: (i - le) >= n

    def combo(i, d, le):
        return trend(e200)(i, d, le) and dist[i] >= 1.0 and (i - le) >= 20

    def combo_slope(i, d, le):
        return trend(e200)(i, d, le) and dist[i] >= 1.0 and slope[i] * d > 0

    return [
        ("baseline", None),
        ("trend200", trend(e200)),
        ("trend100", trend(e100)),
        ("dist0.5", dist_f(0.5)),
        ("dist1.0", dist_f(1.0)),
        ("dist1.5", dist_f(1.5)),
        ("cd10", cool(10)),
        ("cd20", cool(20)),
        ("cd50", cool(50)),
        ("combo(t200+d1+cd20)", combo),
        ("combo_slope", combo_slope),
    ]


def main():
    os.makedirs("legacy", exist_ok=True)
    results = {}
    for b in (100, 50):
        df = load_bricks(b / 100.0)
        results[b] = {}
        for label, t0, t1 in PERIODS:
            d = df[df.time <= t1].reset_index(drop=True)
            results[b][label] = {}
            for name, gate in build_gates(d):
                tr, eq, s = bt(d, t0, gate)
                results[b][label][name] = (s, eq, tr)

    for b in (100, 50):
        print("=" * 112)
        print(f"RENKO-{b} — entry filters (exit unchanged: opposite cross = reverse)")
        print("=" * 112)
        for label, _, _ in PERIODS:
            print(f"\n{label}")
            print(f"{'filter':22s} {'trades':>7s} {'blocked':>8s} {'P/L $':>10s} {'ret %':>8s} "
                  f"{'PF':>6s} {'win%':>6s} {'DD%':>8s} {'gross $':>10s} {'costs $':>9s}")
            for name in results[b][label]:
                s = results[b][label][name][0]
                print(f"{name:22s} {s['n_trades']:>7d} {s['blocked']:>8d} {s['net_pnl']:>10.2f} "
                      f"{s['return_pct']:>7.2f}% {s['profit_factor']:>6} {s['win_rate']:>5.1f}% "
                      f"{s['max_dd_pct']:>7.2f}% {s['gross']:>10.2f} {s['costs']:>9.2f}")
        print()

    print("=" * 112)
    print("SCOREBOARD — Renko-100, sorted by 2-month (Jan + Feb) net P/L")
    print("=" * 112)
    rows = []
    for n in results[100][PERIODS[1][0]]:
        f = results[100][PERIODS[1][0]][n][0]
        j = results[100][PERIODS[0][0]][n][0]
        rows.append((n, f, j, round(f["net_pnl"] + j["net_pnl"], 2)))
    rows.sort(key=lambda r: -r[3])
    print(f"{'filter':22s} {'Feb $':>10s} {'Feb %':>8s} {'Jan $':>10s} {'Jan %':>8s} {'TOTAL $':>10s}")
    for n, f, j, tot in rows:
        print(f"{n:22s} {f['net_pnl']:>10.2f} {f['return_pct']:>7.2f}% {j['net_pnl']:>10.2f} "
              f"{j['return_pct']:>7.2f}% {tot:>10.2f}")
    best, base = rows[0], [r for r in rows if r[0] == "baseline"][0]
    print(f"\n>>> BEST: {best[0]}  (2-month ${best[3]:.2f}) vs baseline ${base[3]:.2f}"
          f"  -> improvement ${best[3]-base[3]:.2f}")
    print(f"    Feb {best[1]['return_pct']:+.2f}% (PF {best[1]['profit_factor']}, "
          f"{best[1]['n_trades']} trades) | Jan {best[2]['return_pct']:+.2f}%")

    # same best filter on Renko-50 (does it rescue the small brick too?)
    print("\nRenko-50 with the same filters (Feb / Jan):")
    for n in [best[0], "baseline", "combo(t200+d1+cd20)"]:
        f = results[50][PERIODS[1][0]][n][0]
        j = results[50][PERIODS[0][0]][n][0]
        print(f"  {n:22s} Feb {f['return_pct']:>7.2f}% ({f['n_trades']:>4d} trd) | "
              f"Jan {j['return_pct']:>7.2f}% ({j['n_trades']:>4d} trd)")

    # ---------------- chart ----------------
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    show = ["baseline", "trend200", "dist1.0", "combo(t200+d1+cd20)", "combo_slope"]
    colors = ["#888888", "#1f77b4", "#2ca02c", "#ff7f0e", "#d62728"]
    for ax, (label, t0, t1) in zip(axes, PERIODS):
        for nm, c in zip(show, colors):
            s, eq, _ = results[100][label][nm]
            ax.plot(eq.time, eq.equity, color=c, lw=1.8,
                    label=f"{nm}: {s['return_pct']:+.1f}% ({s['n_trades']} trd)")
        ax.axhline(BALANCE0, color="k", ls=":", lw=1)
        ax.set_title(f"Renko-100 + EMA 9/12 + new filters — {label}", fontsize=11)
        ax.set_ylabel("Equity ($)")
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    fig.suptitle("New filter test — real M1 bricks, 0.10 lot, spread $0.35 + slip $0.10", fontsize=12)
    fig.tight_layout()
    fig.savefig("legacy/filters_compare.png", dpi=110)
    print("\nSaved legacy/filters_compare.png")


if __name__ == "__main__":
    main()
