"""
Faithful port of EmaCrossBot.cs (cTrader cAlgo) to a bar-replay backtester.

Ported rules, one-for-one with the C# source:
  * 5M EMA9/12 crossover sets _direction5m (1/-1). It LATCHES: no crossover
    means the previous direction stays.
  * 5M body-overlap filter: compare the just-closed 5M bar's BODY (open..close,
    wicks ignored) with the previous N bodies; if any overlap -> block NEW entries
    only (existing positions untouched).
  * 1M EMA6/9 crossover is the entry trigger, but only when it agrees with
    _direction5m.
  * 1M reverse crossover closes the position regardless of P/L. Exit is evaluated
    BEFORE entry on the same bar, exactly as HandleExitOnReverseCrossover() runs
    before TryOpenPosition().
  * Money-based tiered trailing stop:
        if profit < TrailingStartProfit: inactive
        steps = floor((profit - start) / step)
        target = min(initial + steps*step, maxProtected)
        protected profit never decreases
    In cAlgo the stop price is derived from live profit-per-price ratio; with a
    linear USD-per-$1-move contract that reduces exactly to
        stopPrice = entry +/- target/qty
    which is what we use (qty = lots * contractSize).

  * Signals are evaluated on CLOSED bars only (idx = Count-2), so there is no
    look-ahead. We reproduce that by acting on bar i using EMA values of bar i.

Intrabar convention: when a bar could hit the trailing stop, we assume the stop
fills at the stop price. If a bar both triggers the stop and would have produced
a reverse-cross exit, the STOP wins (it is checked first, as OnTick runs
ManageTrailingStops() before the bar-close handlers).
"""
import numpy as np
import pandas as pd

COLS = ["date", "time", "open", "high", "low", "close", "vol"]


def load_all():
    frames = []
    for y in (2021, 2022, 2023, 2024, 2025):
        d = pd.read_csv(f"/home/user/data/repo/DAT_MT_XAUUSD_M1_{y}.csv",
                        header=None, names=COLS)
        d["dt"] = pd.to_datetime(d["date"] + " " + d["time"], format="%Y.%m.%d %H:%M")
        frames.append(d[["dt", "open", "high", "low", "close"]])
    a = pd.concat(frames, ignore_index=True)

    b = pd.read_csv("/home/user/data/gd/XAUUSD_1m.csv")
    b["dt"] = pd.to_datetime(b["datetime"], utc=True).dt.tz_localize(None)
    b = b[["dt", "open", "high", "low", "close"]]

    out = []
    for df in (a, b):
        df = df.sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
        out.append(df.reset_index(drop=True))
    return out


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def build(df, f1=6, s1=9, f5=9, s5=12, overlap_lookback=1):
    """Attach 1M cross flags, latched 5M direction and the body-overlap flag."""
    c = df["close"].to_numpy(float)

    # ---------- 1M EMA 6/9 ----------
    a1 = ema(c, f1)
    b1 = ema(c, s1)
    pa, pb = np.roll(a1, 1), np.roll(b1, 1)
    up1 = (pa <= pb) & (a1 > b1)
    dn1 = (pa >= pb) & (a1 < b1)
    up1[0] = dn1[0] = False
    df["up1"], df["dn1"] = up1, dn1

    # ---------- 5M bars (resample from 1M) ----------
    g = df.set_index("dt").resample("5min").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last")).dropna()

    f5v = ema(g["close"].to_numpy(), f5)
    s5v = ema(g["close"].to_numpy(), s5)
    pf, ps = np.roll(f5v, 1), np.roll(s5v, 1)
    up5 = (pf <= ps) & (f5v > s5v)
    dn5 = (pf >= ps) & (f5v < s5v)
    up5[0] = dn5[0] = False

    # latched direction, as _direction5m in the bot
    dirv = np.zeros(len(g), dtype=int)
    cur = 0
    for i in range(len(g)):
        if up5[i]:
            cur = 1
        elif dn5[i]:
            cur = -1
        dirv[i] = cur

    # body overlap of bar i against previous `overlap_lookback` bodies
    o = g["open"].to_numpy(); cl = g["close"].to_numpy()
    bh = np.maximum(o, cl); bl = np.minimum(o, cl)
    ov = np.zeros(len(g), dtype=bool)
    for i in range(len(g)):
        for k in range(1, overlap_lookback + 1):
            j = i - k
            if j < 0:
                break
            if bl[i] <= bh[j] and bh[i] >= bl[j]:
                ov[i] = True
                break
    g["dir5"] = dirv
    g["ovl"] = ov

    # A 5M bar that closes at time T is only *known* to the 1M stream from T
    # onward. g.index holds bar OPEN times, so the bar opening at T closes at
    # T+5min; shift by one bucket to avoid look-ahead.
    g_shift = g[["dir5", "ovl"]].shift(1)
    buck = df["dt"].dt.floor("5min")
    df["dir5"] = buck.map(g_shift["dir5"]).to_numpy()
    df["ovl"] = buck.map(g_shift["ovl"]).to_numpy()
    df["ovl"] = df["ovl"].fillna(False).astype(bool)
    return df


def run(df, lots=0.01, contract=100.0, spread=0.20,
        trail_on=True, start_profit=4.0, initial_prot=1.0,
        step=1.0, max_prot=3.0, use_overlap=True, label=""):
    """
    qty = lots * contract  -> USD per $1 price move.
    Default 0.01 lots on XAUUSD (contract 100 oz) = $1 per $1 move.
    spread is charged once per round trip, in price units.
    """
    qty = lots * contract
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    up1 = df["up1"].to_numpy(); dn1 = df["dn1"].to_numpy()
    d5 = df["dir5"].to_numpy(); ovl = df["ovl"].to_numpy()
    dt = df["dt"].to_numpy()
    n = len(df)

    pos = 0
    entry = 0.0
    ei = 0
    prot = 0.0          # protected profit already locked ($)
    stop = np.nan       # current stop price
    trades = []

    def close_at(i, px, reason):
        nonlocal pos, prot, stop
        pnl = (px - entry) * qty * pos - spread * qty
        trades.append(dict(entry_time=dt[ei], exit_time=dt[i], side=pos,
                           entry=entry, exit=px, pnl=pnl,
                           bars=i - ei, reason=reason))
        pos = 0
        prot = 0.0
        stop = np.nan

    for i in range(40, n):
        if np.isnan(d5[i]):
            continue

        # ---- 1) trailing stop can fire intrabar (OnTick runs first) ----
        if pos != 0 and not np.isnan(stop):
            if pos > 0 and l[i] <= stop:
                close_at(i, stop, "trail")
            elif pos < 0 and h[i] >= stop:
                close_at(i, stop, "trail")

        # ---- 2) reverse 1M crossover closes, regardless of P/L ----
        if pos > 0 and dn1[i]:
            close_at(i, c[i], "reverse")
        elif pos < 0 and up1[i]:
            close_at(i, c[i], "reverse")

        # ---- 3) entry: 1M cross must agree with latched 5M dir, no overlap ----
        if pos == 0:
            blocked = use_overlap and ovl[i]
            if up1[i] and d5[i] == 1 and not blocked:
                pos = 1; entry = c[i]; ei = i; prot = 0.0; stop = np.nan
            elif dn1[i] and d5[i] == -1 and not blocked:
                pos = -1; entry = c[i]; ei = i; prot = 0.0; stop = np.nan

        # ---- 4) update tiered money trailing stop on this bar's extreme ----
        if pos != 0 and trail_on:
            # best profit reached so far on this bar (mark-to-market)
            best = (h[i] - entry) * qty if pos > 0 else (entry - l[i]) * qty
            if best >= start_profit:
                steps = np.floor((best - start_profit) / step)
                target = min(initial_prot + steps * step, max_prot)
                if target > prot:
                    prot = target
                    stop = entry + (target / qty) if pos > 0 else entry - (target / qty)

    t = pd.DataFrame(trades)
    return stats(t, label), t


def stats(t, label=""):
    if len(t) == 0:
        return dict(label=label, trades=0)
    p = t["pnl"].to_numpy()
    eq = np.cumsum(p)
    dd = eq - np.maximum.accumulate(eq)
    w = p[p > 0]; ls = p[p <= 0]
    gp = w.sum(); gl = -ls.sum()
    return dict(label=label, trades=len(t), win_rate=100 * len(w) / len(p),
                net=p.sum(), pf=(gp / gl if gl else np.inf),
                max_dd=dd.min(), avg=p.mean(),
                avg_win=w.mean() if len(w) else 0.0,
                avg_loss=ls.mean() if len(ls) else 0.0,
                best=p.max(), worst=p.min())
