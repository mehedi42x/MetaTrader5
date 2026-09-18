"""M1 trades + M15 EMA 9/12 direction filter (multi-timeframe test).

The idea: keep trading the M1 EMA 9/12 crossover, but only in the direction the
higher timeframe agrees with — direction taken from the M15 EMA 9/12 crossing:

    M15 EMA9 above EMA12  -> only LONG entries on M1
    M15 EMA9 below EMA12  -> only SHORT entries on M1
    (opposite M1 cross always closes the trade; a new one only opens if the
     M15 direction allows it)

No lookahead: an M15 candle's state is only used after that candle has closed
(see src.strategy.add_mtf_direction).

Variants compared (same window, same costs, fixed 0.10 lot, spread 20 pts only):
  1. M1 raw              — M1 crossover, no direction filter (previous result)
  2. M1 + M15 direction  — the request
  3. M1 + M15 filter + M15 flip also reverses (direction flips close/reverse)
  4. M15 only            — reference: trading the M15 cross itself

Usage:  python3 run_mtf_backtest.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.strategy import add_indicators, add_signals, add_mtf_direction, PARAMS
from src.backtest import run_backtest

DATA = "data/xauusd_m1_slice.csv"
M15_MIN = 15
BALANCE0 = 10_000.0
FIXED_LOT = 0.10
SPREAD = 0.20              # 20 points = $0.20/oz (spread only)
SLIPPAGE = 0.00
OZ = FIXED_LOT * 100.0
PERIODS = [
    ("Feb-2022 (last 30 days)", "2022-02-02 16:59", "2022-03-04 23:59"),
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
]


def resample_ohlc(m1, minutes):
    g = (m1.set_index("time").resample(f"{minutes}min")
         .agg(open=("open", "first"), high=("high", "max"),
              low=("low", "min"), close=("close", "last"), n=("close", "size")))
    return g[g.n > 0].drop(columns="n").reset_index()


def add_m15_flip_signals(df, mtf_candles):
    """Variant 3: when the M15 EMA state flips, treat it as a signal too."""
    mtf = mtf_candles.copy()
    mtf["ema_fast"] = mtf["close"].ewm(span=PARAMS["ema_fast"], adjust=False).mean()
    mtf["ema_slow"] = mtf["close"].ewm(span=PARAMS["ema_slow"], adjust=False).mean()
    state = np.sign(mtf["ema_fast"] - mtf["ema_slow"]).fillna(0).astype(int)
    flip = state.diff().fillna(0).astype(int)
    known_at = pd.to_datetime(mtf["time"]) + pd.Timedelta(minutes=M15_MIN)
    flips = pd.DataFrame({"time": known_at, "flip": flip})[flip != 0]
    out = df.merge(flips, on="time", how="left")
    out["signal_combined"] = out["signal"]
    mask = out["flip"].fillna(0).astype(int) != 0
    out.loc[mask & (out["flip"] > 0), "signal_combined"] = 1
    out.loc[mask & (out["flip"] < 0), "signal_combined"] = -1
    return out.drop(columns=["flip"])


def run(df, t0, t1, entry_filter=None, signal_col="signal"):
    d = df[df.time <= t1].copy().reset_index(drop=True)
    if signal_col != "signal":
        d["signal"] = d[signal_col]
    tr, eq, s = run_backtest(d, t0, balance0=BALANCE0, spread=SPREAD, slippage=SLIPPAGE,
                             exit_mode="reverse", fixed_lot=FIXED_LOT,
                             entry_filter=entry_filter)
    return tr, eq, s


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    m15 = resample_ohlc(m1, M15_MIN)

    df = add_signals(add_indicators(m1))
    df = add_mtf_direction(df, m15, PARAMS["ema_fast"], PARAMS["ema_slow"], M15_MIN)
    df = add_m15_flip_signals(df, m15)

    n_long_ok = int(((df.signal == 1) & (df.mtf_dir == 1)).sum())
    n_short_ok = int(((df.signal == -1) & (df.mtf_dir == -1)).sum())
    n_sig = int((df.signal != 0).sum())
    print(f"M1 bars {len(df)} | M1 crosses {n_sig} | aligned with M15 direction: "
          f"{n_long_ok + n_short_ok} ({(n_long_ok + n_short_ok) / n_sig * 100:.1f}%)")
    print(f"setup: spread {int(SPREAD * 100)} pts = ${SPREAD}/oz, "
          f"${(SPREAD + SLIPPAGE) * OZ:.2f} per 0.10-lot trade\n")

    variants = [
        ("M1 raw (no filter)", dict(signal_col="signal", entry_filter=None)),
        ("M1 + M15 direction", dict(signal_col="signal", entry_filter=dict(mtf=True))),
        ("M1+M15 dir + M15 flip reverses",
         dict(signal_col="signal_combined", entry_filter=dict(mtf=True))),
    ]
    res, curves = {}, {}
    for label, t0, t1 in PERIODS:
        for name, kw in variants:
            tr, eq, s = run(df, t0, t1, **kw)
            res[(name, label)] = (s, tr)
            if "Feb" in label:
                curves[name] = eq
        # reference: M15 cross itself
        m15df = add_signals(add_indicators(m15))
        _, eq15, s15 = run(m15df, t0, t1)
        res[("M15 cross only (reference)", label)] = (s15, None)
        if "Feb" in label:
            curves["M15 cross only (reference)"] = eq15

    for label, _, _ in PERIODS:
        print(f"=== {label} ===")
        print(f"{'variant':32s} {'trades':>7s} {'win%':>6s} {'P/L $':>10s} {'ret %':>8s} "
              f"{'PF':>6s} {'DD%':>8s} {'costs $':>9s} {'gross $':>10s}")
        for name, _ in variants + [("M15 cross only (reference)", None)]:
            s = res[(name, label)][0]
            costs = s["n_trades"] * (SPREAD + SLIPPAGE) * OZ
            print(f"{name:32s} {s['n_trades']:>7d} {s['win_rate']:>5.1f}% {s['net_pnl']:>10.2f} "
                  f"{s['return_pct']:>7.2f}% {s['profit_factor']:>6} {s['max_dd_pct']:>7.2f}% "
                  f"{costs:>9.2f} {s['net_pnl'] + costs:>10.2f}")
        print()

    # ---- chart ----
    colors = {"M1 raw (no filter)": "#888888", "M1 + M15 direction": "#1f77b4",
              "M1+M15 dir + M15 flip reverses": "#2ca02c",
              "M15 cross only (reference)": "#ff7f0e"}
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    for ax, (label, t0, t1) in zip(axes, PERIODS):
        for name, c in colors.items():
            eq = curves[name]
            s = res[(name, label)][0]
            ax.plot(pd.to_datetime(eq["time"]), eq["equity"], color=c, lw=1.5,
                    label=f"{name}: {s['return_pct']:+.1f}% ({s['n_trades']} trd, PF {s['profit_factor']})")
        ax.axhline(BALANCE0, color="k", ls=":", lw=1)
        ax.set_title(f"M1 trades + M15 EMA 9/12 direction — {label}", fontsize=11)
        ax.set_ylabel("Equity ($)")
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    fig.suptitle("M1 EMA 9/12 crossover with M15 EMA 9/12 direction filter — "
                 "spread 20 pts only, 0.10 lot, real M1 data", fontsize=12)
    fig.tight_layout()
    fig.savefig("results/mtf_filter.png", dpi=120)
    print("Saved results/mtf_filter.png")

    # ---- best variant verdict ----
    feb = PERIODS[0][0]
    jan = PERIODS[1][0]
    best = max(variants + [("M15 cross only (reference)", None)],
               key=lambda v: res[(v[0], feb)][0]["net_pnl"] + res[(v[0], jan)][0]["net_pnl"])
    base = res[("M1 raw (no filter)", feb)][0]["net_pnl"] + res[("M1 raw (no filter)", jan)][0]["net_pnl"]
    tot = res[(best[0], feb)][0]["net_pnl"] + res[(best[0], jan)][0]["net_pnl"]
    print(f"\n>>> best over Jan+Feb: {best[0]}  (${tot:.2f})  vs M1 raw (${base:.2f})"
          f"  -> improvement ${tot - base:.2f}")


if __name__ == "__main__":
    main()
