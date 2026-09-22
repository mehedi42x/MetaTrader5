"""
Strategy: 5M EMA 9/12 trend + 1M EMA 2/3 cross entry, fixed TP / SL.

Pip convention for XAUUSD: 1 pip = $0.10  ->  10 pips = $1.00
(A "point" of $1.00 would be 100 pips; we test both so nothing is ambiguous.)

Intrabar rule: if a bar's range touches BOTH tp and sl we assume the WORSE
outcome (SL first). That keeps the result honest rather than flattering.
"""
import numpy as np
import pandas as pd

COLS = ["date", "time", "open", "high", "low", "close", "vol"]


def load_all():
    """2021-2025 (tiumbj) + 2026 Mar-Sep (getdata). Returns list of frames."""
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
        out.append(df)
    return out


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def features(df, f1=2, s1=3, f5=9, s5=12, htf="5min"):
    c = df["close"].to_numpy(float)
    # ---- 1M fast cross (entry trigger) ----
    a = ema(c, f1); b = ema(c, s1)
    df["e1f"], df["e1s"] = a, b
    pa, pb = np.roll(a, 1), np.roll(b, 1)
    bull = (a > b) & (pa <= pb)
    bear = (a < b) & (pa >= pb)
    bull[0] = bear[0] = False
    df["bull1"], df["bear1"] = bull, bear

    # ---- 5M trend, non-repainting (value of the PREVIOUS closed 5M bar) ----
    g = df.set_index("dt")["close"].resample(htf).last().dropna()
    hf = pd.Series(ema(g.to_numpy(), f5), index=g.index).shift(1)
    hs = pd.Series(ema(g.to_numpy(), s5), index=g.index).shift(1)
    buck = df["dt"].dt.floor(htf)
    df["h5f"] = buck.map(hf).to_numpy()
    df["h5s"] = buck.map(hs).to_numpy()
    df["bull5"] = df["h5f"] > df["h5s"]
    df["bear5"] = df["h5f"] < df["h5s"]

    # 5M cross bars (for the "5M cross" entry variant)
    hb = df["bull5"].to_numpy()
    df["cross5up"] = hb & ~np.roll(hb, 1)
    hbr = df["bear5"].to_numpy()
    df["cross5dn"] = hbr & ~np.roll(hbr, 1)
    return df


def run(df, tp=1.0, sl=1.0, spread=0.2, qty=1.0,
        mode="trend", window=0, one_per_5m=False, label=""):
    """
    mode='trend'  : enter on 1M cross whenever it agrees with the 5M trend
    mode='cross5' : enter on 1M cross only within `window` bars AFTER a 5M cross
    """
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    bull1 = df["bull1"].to_numpy(); bear1 = df["bear1"].to_numpy()
    bull5 = df["bull5"].to_numpy(); bear5 = df["bear5"].to_numpy()
    c5u = df["cross5up"].to_numpy(); c5d = df["cross5dn"].to_numpy()
    dt = df["dt"].to_numpy()
    n = len(df)

    if mode == "cross5":
        ageU = np.full(n, 10**9); ageD = np.full(n, 10**9)
        au = ad = 10**9
        for i in range(n):
            au = 0 if c5u[i] else au + 1
            ad = 0 if c5d[i] else ad + 1
            ageU[i] = au; ageD[i] = ad
        okL = ageU <= window
        okS = ageD <= window
    else:
        okL = bull5
        okS = bear5

    pos = 0; entry = 0.0; ei = 0
    used5 = -1
    trades = []

    def close_at(i, px, reason):
        nonlocal pos
        pnl = (px - entry) * qty * pos - spread * qty
        trades.append(dict(entry_time=dt[ei], exit_time=dt[i], side=pos,
                           entry=entry, exit=px, pnl=pnl,
                           bars=i - ei, reason=reason))
        pos = 0

    for i in range(30, n):
        if pos != 0:
            # pessimistic: check SL before TP on the same bar
            if pos > 0:
                if l[i] <= entry - sl:
                    close_at(i, entry - sl, "sl")
                elif h[i] >= entry + tp:
                    close_at(i, entry + tp, "tp")
            else:
                if h[i] >= entry + sl:
                    close_at(i, entry + sl, "sl")
                elif l[i] <= entry - tp:
                    close_at(i, entry - tp, "tp")

        if pos == 0:
            if bull1[i] and okL[i]:
                pos = 1; entry = c[i]; ei = i
            elif bear1[i] and okS[i]:
                pos = -1; entry = c[i]; ei = i

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
                avg_win=w.mean() if len(w) else 0,
                avg_loss=ls.mean() if len(ls) else 0,
                best=p.max(), worst=p.min())
