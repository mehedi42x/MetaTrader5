"""M1 entries + "hold losers until the 5-minute reverse cross" exit rule.

Rules (exactly as requested):
  * ENTRY  : M1 EMA9/EMA12 crossover (BUY on cross up, SELL on cross down).
  * TP     : when an M1 reverse cross happens while the trade is IN PROFIT,
             the trade is closed there — and (like the classic reverse system)
             a new trade is opened in the cross direction.
  * HOLD   : when the M1 reverse cross happens while the trade is in LOSS, the
             trade is NOT closed. It is kept (the M1 signal is ignored while it
             is held) until either
               a) a later M1 reverse cross catches it in profit  -> close (TP), or
               b) the M5 EMA9/EMA12 produces a reverse cross against it -> close (SL).
  * Lot   : 0.01 (1 oz), fixed.  Cost: spread only, 20 points = $0.20/oz
            -> 0.20 x 1 oz = $0.20 per round trip at 0.01 lot.
  * Leverage: 1:1000 — margin = notional / 1000 (margin is tracked for the
            margin-call check; leverage itself does not change P/L per lot).

Usage:  python3 run_hybrid_backtest.py
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
OZ = FIXED_LOT * 100.0          # 0.01 lot = 1 oz
SPREAD = 0.20                   # 20 points = $0.20/oz (round trip)
COST = SPREAD * OZ              # $0.20 per trade at 0.01 lot
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
    """Flag, on each M1 bar, whether an M5 EMA9/12 cross became known at that bar."""
    m5 = add_ema_cols(m5)
    up = m5[m5.sig == 1].copy()
    dn = m5[m5.sig == -1].copy()
    # an M5 candle's state is known at its CLOSE (time is the candle start)
    up_t = (pd.to_datetime(up["time"]) + pd.Timedelta(minutes=tf_minutes)).to_numpy()
    dn_t = (pd.to_datetime(dn["time"]) + pd.Timedelta(minutes=tf_minutes)).to_numpy()
    t = pd.to_datetime(m1["time"]).to_numpy()
    bull = np.zeros(len(t), dtype=bool)
    bear = np.zeros(len(t), dtype=bool)
    bu = np.searchsorted(t, up_t, side="left")
    bd = np.searchsorted(t, dn_t, side="left")
    bull[bu[bu < len(t)]] = True
    bear[bd[bd < len(t)]] = True
    return bull, bear


def bt_hybrid(df, t0, t1, bull5, bear5, balance0=BALANCE0, profit_check="gross",
              use_mtf=False):
    """Engine for the hybrid exit rule. Returns (trades, equity, stats).

    use_mtf=True additionally only ENTERS (or re-enters after a TP) when the
    M15 EMA9/12 direction agrees with the M1 signal — a filter on entries only,
    the exit rules stay exactly as requested."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()
    sig = df["sig"].to_numpy()
    mtf = df["mtf_dir"].to_numpy() if use_mtf else None
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    end = np.searchsorted(t, np.datetime64(pd.to_datetime(t1)), side="right")

    def mtf_ok(i, d):
        return True if mtf is None else (mtf[i] * d > 0)

    bal = balance0
    trades, eq_ts, eq_val = [], [], []
    pos = None
    n_tp = n_sl = n_held_signal = 0

    def close(price, when, idx, reason):
        nonlocal bal, pos, n_tp, n_sl
        gross = (price - pos["entry"]) * pos["dir"] * OZ
        pnl = gross - COST
        bal += pnl
        trades.append(dict(entry_time=pos["t"], exit_time=when,
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(price, 2),
                           sl=float("nan"), tp=float("nan"), lot=FIXED_LOT,
                           pnl=round(pnl, 2), r_multiple=0.0,
                           bars_held=int(idx - pos["idx"]), exit_reason=reason))
        if reason == "TP":
            n_tp += 1
        else:
            n_sl += 1
        pos = None

    for i in range(1, min(len(df), end)):        # never trade past t1
        actionable = i >= start
        s = int(sig[i - 1]) if actionable else 0

        if pos is not None:
            # a) M1 reverse cross while in profit -> TP close (+ reverse entry)
            if s != 0 and s != pos["dir"]:
                unreal = (c[i - 1] - pos["entry"]) * pos["dir"] * OZ
                if profit_check == "net":
                    unreal -= COST
                if unreal > 0:
                    close(o[i], t[i], i, "TP")
                    if mtf_ok(i - 1, s):         # classic reverse (filtered if use_mtf)
                        pos = dict(dir=s, entry=o[i], t=t[i], idx=i)
                else:
                    n_held_signal += 1           # held through the reverse cross
            # b) M5 reverse cross against the held trade while in loss -> SL close
            if pos is not None:
                m5_against = (bear5[i] if pos["dir"] == 1 else bull5[i])
                if m5_against:
                    unreal = (o[i] - pos["entry"]) * pos["dir"] * OZ
                    if profit_check == "net":
                        unreal -= COST
                    if unreal <= 0:
                        close(o[i], t[i], i, "SL5M")
        if pos is None and s != 0 and mtf_ok(i - 1, s):
            pos = dict(dir=s, entry=o[i], t=t[i], idx=i)

        eq_ts.append(t[i])
        eq_val.append(bal)

    last = min(len(df), end) - 1
    if pos is not None:
        close(float(c[last]), t[last], last, "END")

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame({"time": pd.to_datetime(eq_ts), "equity": eq_val})
    eq = eq[eq.time >= pd.to_datetime(t0)].reset_index(drop=True)
    stats = compute_stats(tr, eq, balance0) if len(tr) else dict(n_trades=0)
    stats["tp_exits"] = n_tp
    stats["sl5m_exits"] = n_sl
    stats["held_through_signal"] = n_held_signal
    if stats.get("n_trades"):
        stats["costs"] = round(stats["n_trades"] * COST, 2)
    return tr, eq, stats


def bt_plain(df, t0, t1, balance0=BALANCE0):
    """Classic: every M1 reverse cross closes and reverses (reference)."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()
    sig = df["sig"].to_numpy()
    start = np.searchsorted(t, np.datetime64(pd.to_datetime(t0)))
    end = np.searchsorted(t, np.datetime64(pd.to_datetime(t1)), side="right")
    bal = balance0
    trades, eq_ts, eq_val = [], [], []
    pos = None
    for i in range(1, min(len(df), end)):
        if i >= start and sig[i - 1] != 0:
            d = int(sig[i - 1])
            if pos is not None and pos["dir"] != d:
                bal += (o[i] - pos["entry"]) * pos["dir"] * OZ - COST
                trades.append(dict(entry_time=pos["t"], exit_time=t[i],
                                   direction="LONG" if pos["dir"] == 1 else "SHORT",
                                   entry=round(pos["entry"], 2), exit=round(o[i], 2),
                                   pnl=round((o[i] - pos["entry"]) * pos["dir"] * OZ - COST, 2),
                                   r_multiple=0.0, bars_held=i - pos["idx"],
                                   exit_reason="REV"))
                pos = None
            if pos is None:
                pos = dict(dir=d, entry=o[i], t=t[i], idx=i)
        eq_ts.append(t[i])
        eq_val.append(bal)
    last = min(len(df), end) - 1
    if pos is not None:
        bal += (c[last] - pos["entry"]) * pos["dir"] * OZ - COST
        trades.append(dict(entry_time=pos["t"], exit_time=t[last],
                           direction="LONG" if pos["dir"] == 1 else "SHORT",
                           entry=round(pos["entry"], 2), exit=round(c[last], 2),
                           pnl=round((c[last] - pos["entry"]) * pos["dir"] * OZ - COST, 2),
                           r_multiple=0.0, bars_held=last - pos["idx"], exit_reason="END"))
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
    m1 = add_mtf_direction(m1, m15, 9, 12, 15)   # M15 EMA9/12 direction per M1 bar

    print(f"M1 bars {len(m1)} | M5 bars {len(m5)}")
    print(f"Sizing: lot {FIXED_LOT} = {OZ:.0f} oz | spread ${SPREAD}/oz "
          f"-> ${COST:.2f} per trade | leverage 1:{LEVERAGE} "
          f"(margin for 1 oz @ ~$1800 = ${1800 / LEVERAGE:.2f})\n")
    print("Why 0.10 lot cost $2:  cost = spread x ounces = 0.20 x 10 oz = $2.00")
    print("At 0.01 lot it is exactly:  0.20 x 1 oz = $0.20 per round trip.\n")

    variants = {
        "M1 raw (every cross closes)": lambda d, a, b: bt_plain(d, a, b),
        "HYBRID (loss held, M5 SL)": lambda d, a, b: bt_hybrid(d, a, b, bull5, bear5, profit_check="gross"),
        "HYBRID net-profit check": lambda d, a, b: bt_hybrid(d, a, b, bull5, bear5, profit_check="net"),
        "HYBRID + M15 direction": lambda d, a, b: bt_hybrid(d, a, b, bull5, bear5, use_mtf=True),
    }
    res, curves = {}, {}
    for label, t0, t1 in PERIODS:
        for name, fn in variants.items():
            tr, eq, s = fn(m1, t0, t1)
            res[(name, label)] = (s, tr)
            if "Feb" in label:
                curves[name] = eq

    for label, _, _ in PERIODS:
        print(f"=== {label} (0.01 lot, spread $0.20/trade) ===")
        print(f"{'variant':30s} {'trades':>7s} {'win%':>6s} {'P/L $':>9s} {'ret %':>8s} "
              f"{'PF':>6s} {'DD $':>9s} {'DD%':>7s} {'costs $':>8s} {'TP/SL':>9s}")
        for name in variants:
            s = res[(name, label)][0]
            tpsl = (f"{s.get('tp_exits', '-')}/{s.get('sl5m_exits', '-')}"
                    if "HYBRID" in name else "-")
            print(f"{name:30s} {s['n_trades']:>7d} {s['win_rate']:>5.1f}% {s['net_pnl']:>9.2f} "
                  f"{s['return_pct']:>7.2f}% {s['profit_factor']:>6} {s['max_dd_usd']:>9.2f} "
                  f"{s['max_dd_pct']:>6.2f}% {s['costs']:>8.2f} {tpsl:>9s}")
        print()

    # margin / leverage check for the hybrid on Feb
    s = res[("HYBRID (loss held, M5 SL)", PERIODS[0][0])][0]
    tr = res[("HYBRID (loss held, M5 SL)", PERIODS[0][0])][1]
    if len(tr):
        hold = (pd.to_datetime(tr.exit_time) - pd.to_datetime(tr.entry_time))
        print(f"Hybrid Feb: {s['n_trades']} trades | TP exits {s['tp_exits']} | "
              f"M5-SL exits {s['sl5m_exits']} | held through M1 cross "
              f"{s['held_through_signal']} times")
        print(f"  avg hold {hold.mean()}, longest {hold.max()} | "
              f"worst trade ${tr.pnl.min():.2f} | best ${tr.pnl.max():.2f}")
        print(f"  margin per trade @1:{LEVERAGE} ~ ${tr.entry.mean() * OZ / LEVERAGE:.2f} "
              f"-> end balance ${s['end_balance']:,.2f}")

    # ---- chart ----
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    colors = {"M1 raw (every cross closes)": "#888888",
              "HYBRID (loss held, M5 SL)": "#1f77b4",
              "HYBRID net-profit check": "#2ca02c",
              "HYBRID + M15 direction": "#ff7f0e"}
    for ax, (label, t0, t1) in zip(axes, PERIODS):
        for name, c in colors.items():
            eq = curves[name]
            st = res[(name, label)][0]
            ax.plot(pd.to_datetime(eq["time"]), eq["equity"], color=c, lw=1.5,
                    label=f"{name}: {st['return_pct']:+.2f}% ({st['n_trades']} trd, "
                          f"PF {st['profit_factor']})")
        ax.axhline(BALANCE0, color="k", ls=":", lw=1)
        ax.set_title(f"M1 entries, profit=TP on M1 cross / loss held to M5 SL — {label}",
                     fontsize=10.5)
        ax.set_ylabel("Equity ($)")
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    fig.suptitle("Hybrid exit test — 0.01 lot, spread $0.20/oz only, leverage 1:1000, "
                 "real XAUUSD M1 data", fontsize=12)
    fig.tight_layout()
    fig.savefig("results/hybrid_m1_m5.png", dpi=120)
    print("\nSaved results/hybrid_m1_m5.png")

    feb = PERIODS[0][0]
    jan = PERIODS[1][0]
    for name in variants:
        tot = res[(name, feb)][0]["net_pnl"] + res[(name, jan)][0]["net_pnl"]
        print(f"{name:30s} 2-month total: ${tot:.2f}")


if __name__ == "__main__":
    main()
