"""EVERY signal = a trade. Multiple positions in parallel (no signal ignored).

Rule set:
  * ENTRY : every M1 EMA9/12 cross opens its own trade (BUY on cross up, SELL on
            cross down). Consecutive crosses therefore stack positions — nothing
            is skipped while an older trade is being held.
  * TP    : an M1 reverse cross (against that trade) while the trade is IN PROFIT
            closes that trade at the next M1 open.
  * HOLD  : an M1 reverse cross while the trade is in LOSS does not close it.
  * SL    : a held (losing) trade is closed when the M5 EMA9/12 crosses against it.
  * Order : each trade is managed independently; one trade's state never blocks
            another signal.
  * Lot   : 0.01 (1 oz). Cost: spread only 20 pts = $0.20/oz -> $0.20 per trade.
  * Lev   : 1:1000 (margin per 1 oz ~ $1.87 at gold ~1870).

Variants compared:
  A. EVERY SIGNAL, parallel positions (the request)
  B. EVERY SIGNAL + M15 direction filter (only for reference — filter drops signals)
  C. Classic reverse (1 position, every signal still trades: close + reverse)
  D. EVERY SIGNAL but losers closed immediately on the M1 cross too (no hold)

Usage:  python3 run_all_signals.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from src.indicators import ema
from src.backtest import compute_stats
from src.strategy import add_mtf_direction

DATA = "data/xauusd_m1_slice.csv"
BALANCE0 = 10_000.0
LEVERAGE = 1000
FIXED_LOT = 0.01
OZ = FIXED_LOT * 100.0          # 1 oz
SPREAD = 0.20
COST = SPREAD * OZ              # $0.20 per round trip
PERIODS = [
    ("Feb-2022 (last 30 days)", "2022-02-02 16:59", "2022-03-04 23:59"),
    ("Jan-2022 (validation)", "2022-01-01", "2022-01-31 23:59"),
]


def add_ema_cols(df, fast=9, slow=12):
    df = df.copy()
    df["ema_fast"] = ema(df["close"], fast)
    df["ema_slow"] = ema(df["close"], slow)
    up = (df.ema_fast.shift(1) <= df.ema_slow.shift(1)) & (df.ema_fast > df.ema_slow)
    dn = (df.ema_fast.shift(1) >= df.ema_slow.shift(1)) & (df.ema_fast < df.ema_slow)
    df["sig"] = 0
    df.loc[up, "sig"] = 1
    df.loc[dn, "sig"] = -1
    df.loc[df[["ema_fast", "ema_slow"]].isna().any(axis=1), "sig"] = 0
    return df


def resample_ohlc(m1, minutes):
    g = (m1.set_index("time").resample(f"{minutes}min")
         .agg(open=("open", "first"), high=("high", "max"),
              low=("low", "min"), close=("close", "last"), n=("close", "size")))
    return g[g.n > 0].drop(columns="n").reset_index()


def map_m5_crosses_to_m1(m1, m5, tf_minutes=5):
    m5 = add_ema_cols(m5)
    t = pd.to_datetime(m1["time"]).to_numpy()
    out = {}
    for name, s in (("bull", 1), ("bear", -1)):
        times = (pd.to_datetime(m5.loc[m5.sig == s, "time"])
                 + pd.Timedelta(minutes=tf_minutes)).to_numpy()
        idx = np.searchsorted(t, times, side="left")
        flag = np.zeros(len(t), dtype=bool)
        flag[idx[idx < len(t)]] = True
        out[name] = flag
    return out["bull"], out["bear"]


def bt_every_signal(df, t0, t1, bull5, bear5, use_mtf=False, hold_loss=True,
                    balance0=BALANCE0, max_open=None):
    """Every signal opens a trade. Each trade is managed independently.

    hold_loss=True  -> losers survive the M1 reverse cross and wait for the M5 SL
    hold_loss=False -> every M1 reverse cross closes any trade (classic behaviour)
    max_open=None   -> uncapped: EVERY signal is traded (positions stack)
    max_open=N      -> at most N positions at a time (extra signals are skipped)
    """
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()
    sig = df["sig"].to_numpy()
    mtf = df["mtf_dir"].to_numpy() if use_mtf else None
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    end = np.searchsorted(t, np.datetime64(pd.to_datetime(t1)), side="right")

    bal = balance0
    open_pos = []       # list of dicts
    trades, eq_ts, eq_val = [], [], []
    n_tp = n_sl = n_hold = 0
    max_open_seen = 0

    def close(pos, price, when, idx, reason):
        nonlocal bal, n_tp, n_sl
        pnl = (price - pos["entry"]) * pos["dir"] * OZ - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           pnl=round(pnl, 2), r_multiple=0.0,
                           bars_held=int(idx - pos["idx"]), exit_reason=reason))
        if reason == "TP":
            n_tp += 1
        elif reason.startswith("SL"):
            n_sl += 1
        open_pos.remove(pos)

    for i in range(1, min(len(df), end)):
        actionable = i >= start
        s = int(sig[i - 1]) if actionable else 0

        if s != 0:
            # ---- exits caused by this M1 reverse cross ----
            for pos in list(open_pos):
                if pos["dir"] == s:
                    continue
                unreal = (c[i - 1] - pos["entry"]) * pos["dir"] * OZ
                if unreal > 0:
                    close(pos, o[i], t[i], i, "TP")          # profit -> TP
                elif not hold_loss:
                    close(pos, o[i], t[i], i, "SL_M1")       # variant D
                else:
                    n_hold += 1                              # kept, waiting for M5
            # ---- the new trade for this signal ----
            if (mtf is None or mtf[i - 1] * s > 0) and (max_open is None
                                                       or len(open_pos) < max_open):
                open_pos.append(dict(dir=s, entry=o[i], t=t[i], idx=i))

        # ---- M5 SL check for held (losing) trades ----
        for pos in list(open_pos):
            against = bear5[i] if pos["dir"] == 1 else bull5[i]
            if not against:
                continue
            unreal = (o[i] - pos["entry"]) * pos["dir"] * OZ
            if unreal <= 0:
                close(pos, o[i], t[i], i, "SL5M")

        max_open_seen = max(max_open_seen, len(open_pos))
        eq_ts.append(t[i])
        eq_val.append(bal)

    last = min(len(df), end) - 1
    for pos in list(open_pos):      # close leftovers at the last close
        close(pos, float(c[last]), t[last], last, "END")

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    st = compute_stats(tr, eq, balance0) if len(tr) else dict(n_trades=0, net_pnl=0.0,
                                                             return_pct=0.0, profit_factor=0,
                                                             win_rate=0.0, max_dd_usd=0.0,
                                                             max_dd_pct=0.0, costs=0.0)
    st.update(tp_exits=n_tp, sl_exits=n_sl, held_signals=n_hold, max_open=max_open_seen)
    if st.get("n_trades"):
        st["costs"] = round(st["n_trades"] * COST, 2)
    return tr, eq, st


def bt_classic(df, t0, t1, balance0=BALANCE0):
    """Classic reverse: one position, every signal closes+reverses."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()
    sig = df["sig"].to_numpy()
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    end = np.searchsorted(t, np.datetime64(pd.to_datetime(t1)), side="right")
    bal = balance0
    trades, eq_ts, eq_val, pos = [], [], [], None
    for i in range(1, min(len(df), end)):
        if i >= start and sig[i - 1] != 0:
            d = int(sig[i - 1])
            if pos is not None and pos["dir"] != d:
                pnl = (o[i] - pos["entry"]) * pos["dir"] * OZ - COST
                bal += pnl
                trades.append(dict(entry_time=pos["t"], exit_time=t[i],
                                   direction="LONG" if pos["dir"] == 1 else "SHORT",
                                   entry=round(pos["entry"], 2), exit=round(o[i], 2),
                                   pnl=round(pnl, 2), r_multiple=0.0,
                                   bars_held=i - pos["idx"], exit_reason="REV"))
                pos = None
            if pos is None:
                pos = dict(dir=d, entry=o[i], t=t[i], idx=i)
        eq_ts.append(t[i])
        eq_val.append(bal)
    last = min(len(df), end) - 1
    if pos is not None:
        pnl = (c[last] - pos["entry"]) * pos["dir"] * OZ - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=t[last],
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(c[last], 2),
                           pnl=round(pnl, 2), r_multiple=0.0,
                           bars_held=last - pos["idx"], exit_reason="END"))
    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    st = compute_stats(tr, eq, balance0) if len(tr) else dict(n_trades=0)
    if st.get("n_trades"):
        st["costs"] = round(st["n_trades"] * COST, 2)
    return tr, eq, st


def main():
    m1 = pd.read_csv(DATA, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    m1 = add_ema_cols(m1)
    m5 = resample_ohlc(m1, 5)
    bull5, bear5 = map_m5_crosses_to_m1(m1, m5)
    m15 = resample_ohlc(m1, 15)
    m1 = add_mtf_direction(m1, m15, 9, 12, 15)

    print(f"M1 bars {len(m1)} | M5 bars {len(m5)} | 0.01 lot = {OZ:.0f} oz")
    print(f"cost ${COST:.2f}/trade (spread 20 pts) | leverage 1:{LEVERAGE} "
          f"(~${1870 / LEVERAGE:.2f} margin per position)\n")

    variants = {
        "A. ALL signals, uncapped": lambda d, a, b: bt_every_signal(d, a, b, bull5, bear5),
        "B. ALL signals + M15 dir": lambda d, a, b: bt_every_signal(d, a, b, bull5, bear5, use_mtf=True),
        "C. ALL signals cap 2 + M15": lambda d, a, b: bt_every_signal(d, a, b, bull5, bear5, use_mtf=True, max_open=2),
        "D. ALL signals cap 3 + M15": lambda d, a, b: bt_every_signal(d, a, b, bull5, bear5, use_mtf=True, max_open=3),
        "E. Classic reverse (1 pos)": lambda d, a, b: bt_classic(d, a, b),
    }
    res, curves = {}, {}
    for label, t0, t1 in PERIODS:
        n_sig = int(((m1.time >= t0) & (m1.time <= t1) & (m1.sig != 0)).sum())
        print(f"=== {label} — signals in window: {n_sig} ===")
        print(f"{'variant':30s} {'trades':>7s} {'win%':>6s} {'P/L $':>9s} {'ret %':>8s} "
              f"{'PF':>6s} {'DD $':>9s} {'costs $':>8s} {'max open':>8s} {'TP/SL':>9s}")
        for name, fn in variants.items():
            tr, eq, s = fn(m1, t0, t1)
            res[(name, label)] = (s, tr)
            if "Feb" in label:
                curves[name] = eq
            tpsl = f"{s.get('tp_exits', '-')}/{s.get('sl_exits', '-')}"
            print(f"{name:30s} {s['n_trades']:>7d} {s['win_rate']:>5.1f}% {s['net_pnl']:>9.2f} "
                  f"{s['return_pct']:>7.2f}% {s['profit_factor']:>6} {s['max_dd_usd']:>9.2f} "
                  f"{s['costs']:>8.2f} {s.get('max_open', 1):>8d} {tpsl:>9s}")
        print()

    feb, jan = PERIODS[0][0], PERIODS[1][0]
    print("2-month totals (Jan+Feb):")
    for name in variants:
        tot = res[(name, feb)][0]["net_pnl"] + res[(name, jan)][0]["net_pnl"]
        print(f"  {name:30s} ${tot:>9.2f}")

    # detail for variant A
    s = res[("A. ALL signals, uncapped", feb)][0]
    tr = res[("A. ALL signals, uncapped", feb)][1]
    hold = pd.to_datetime(tr.exit_time) - pd.to_datetime(tr.entry_time)
    print(f"\nA (Feb): {s['n_trades']} trades | TP {s['tp_exits']} | SL {s['sl_exits']} | "
          f"held through a reverse cross {s['held_signals']} times | max {s['max_open']} "
          f"positions open at once")
    print(f"  avg hold {hold.mean()} | longest {hold.max()} | worst ${tr.pnl.min():.2f} "
          f"| best ${tr.pnl.max():.2f}")

    # ---- chart ----
    colours = {"A. ALL signals, uncapped": "#1f77b4",
               "B. ALL signals + M15 dir": "#ff7f0e",
               "C. ALL signals cap 2 + M15": "#2ca02c",
               "D. ALL signals cap 3 + M15": "#d62728",
               "E. Classic reverse (1 pos)": "#888888"}
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    for ax, (label, t0, t1) in zip(axes, PERIODS):
        for name, col in colours.items():
            eq = curves[name]
            st = res[(name, label)][0]
            ax.plot(pd.to_datetime(eq["time"]), eq["equity"], color=col, lw=1.5,
                    label=f"{name}: {st['return_pct']:+.2f}% ({st['n_trades']} trd)")
        ax.axhline(BALANCE0, color="k", ls=":", lw=1)
        ax.set_title(f"Every-signal system — {label}", fontsize=11)
        ax.set_ylabel("Equity ($)")
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    fig.suptitle("Every M1 signal = a trade (parallel positions, own TP/SL) — "
                 "0.01 lot, $0.20/trade, 1:1000", fontsize=12)
    fig.tight_layout()
    fig.savefig("results/every_signal.png", dpi=120)
    print("\nSaved results/every_signal.png")


if __name__ == "__main__":
    main()
